import re
from sqlalchemy import types as sqltypes
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy.engine import reflection

class VerticaDialect(PGDialect):
    """ Vertica Dialect using a vertica-python connection and PGDialect """

    name = 'vertica'
    driver = 'vertica_python'
    
    supports_unicode_statements = True
    supports_unicode_binds = True
    supports_native_decimal = True

    ischema_names = {
        'BINARY': sqltypes.BLOB,
        'VARBINARY': sqltypes.BLOB,
        'LONG VARBINARY': sqltypes.BLOB,
        'BYTEA': sqltypes.BLOB,
        'RAW': sqltypes.BLOB,

        'BOOLEAN': sqltypes.BOOLEAN,

        'CHAR': sqltypes.CHAR,
        'VARCHAR': sqltypes.VARCHAR,
        'LONG VARCHAR': sqltypes.VARCHAR,
        'VARCHAR2': sqltypes.VARCHAR,
        'TEXT': sqltypes.VARCHAR,

        'DATE': sqltypes.DATE(),
        'DATETIME': sqltypes.DATETIME(),
        'SMALLDATETIME': sqltypes.DATETIME(),
        'TIME': sqltypes.TIME(),
        'TIMETZ': sqltypes.TIME(timezone=True),
        'TIME WITH TIMEZONE': sqltypes.TIME(timezone=True),
        'TIMESTAMP': sqltypes.TIMESTAMP(),
        'TIMESTAMPTZ': sqltypes.TIMESTAMP(timezone=True),
        'TIMESTAMP WITH TIMEZONE': sqltypes.TIMESTAMP(timezone=True),

        'INTERVAL': INTERVAL,

        # All the same internal representation
        'FLOAT': sqltypes.FLOAT,
        'FLOAT8': sqltypes.FLOAT,
        'DOUBLE': sqltypes.FLOAT,
        'REAL': sqltypes.FLOAT,

        'INT': sqltypes.INTEGER,
        'INTEGER': sqltypes.INTEGER,
        'INT8': sqltypes.INTEGER,
        'BIGINT': sqltypes.INTEGER,
        'SMALLINT': sqltypes.INTEGER,
        'TINYINT': sqltypes.INTEGER,

        'NUMERIC': sqltypes.NUMERIC,
        'DECIMAL': sqltypes.NUMERIC,
        'NUMBER': sqltypes.NUMERIC,
        'MONEY': sqltypes.NUMERIC,
    }


    @classmethod
    def dbapi(cls):
        vp_module = __import__('vertica_python')

        # sqlalchemy expects to find the base Error class here,
        # so we need to alias it
        vp_module.Error = vp_module.errors.Error

        return vp_module


    def create_connect_args(self, url):
        opts = url.translate_connect_args(username='user')
        opts.update(url.query)
        return [[], opts]


    def has_schema(self, connection, schema):
        query = ("SELECT EXISTS (SELECT schema_name FROM v_catalog.schemata "
                 "WHERE schema_name='%s')") % (schema)
        rs = connection.execute(query)
        return bool(rs.scalar())


    def has_table(self, connection, table_name, schema=None):
        if schema is None:
            schema = self._get_default_schema_name(connection)
        query = ("SELECT EXISTS ("
                 "SELECT table_name FROM v_catalog.all_tables "
                 "WHERE schema_name='%s' AND "
                 "table_name='%s'"
                 ")") % (schema, table_name)
        rs = connection.execute(query)
        return bool(rs.scalar())


    def has_sequence(self, connection, sequence_name, schema=None):
        if schema is None:
            schema = self._get_default_schema_name(connection)
        query = ("SELECT EXISTS ("
                 "SELECT sequence_name FROM v_catalog.sequences "
                 "WHERE sequence_schema='%s' AND "
                 "sequence_name='%s'"
                 ")") % (schema, sequence_name)
        rs = connection.execute(query)
        return bool(rs.scalar())


    def has_type(self, connection, type_name, schema=None):
        query = ("SELECT EXISTS ("
                 "SELECT type_name FROM v_catalog.types "
                 "WHERE type_name='%s'"
                 ")") % (type_name)
        rs = connection.execute(query)
        return bool(rs.scalar())


    def _get_server_version_info(self, connection):
        v = connection.scalar("select version()")
        m = re.match(
            '.*Vertica Analytic Database '
            'v(\d+)\.(\d+)\.(\d)+.*',
            v)
        if not m:
            raise AssertionError(
                "Could not determine version from string '%s'" % v)
        return tuple([int(x) for x in m.group(1, 2, 3) if x is not None])


    def _get_default_schema_name(self, connection):
        return connection.scalar("select current_schema()")


    @reflection.cache
    def get_schema_names(self, connection, **kw):
        query = "SELECT schema_name FROM v_catalog.schemata"
        rs = connection.execute(query)
        return [row[0] for row in rs if not row[0].startswith('v_')]


    @reflection.cache
    def get_table_comment(self, connection, table_name, schema=None, **kw):
        schema_conditional = (
            "" if schema is None else "AND object_schema = '{schema}'".format(schema=schema))
        query = """
        SELECT comment FROM v_catalog.comments WHERE object_type = 'TABLE'
        AND object_name = '{table_name}'
        {schema_conditional}
        """.format(table_name=table_name, schema_conditional=schema_conditional)
        rs = connection.execute(query)
        return {"text": rs.scalar()}


    @reflection.cache
    def get_table_names(self, connection, schema=None, **kw):
        s = ["SELECT table_name FROM v_catalog.tables"]
        if schema is not None:
            s.append("WHERE table_schema = '%s'" % (schema,))
        s.append("ORDER BY table_schema, table_name")

        rs = connection.execute(' '.join(s))
        return [row[0] for row in rs]


    @reflection.cache
    def get_view_names(self, connection, schema=None, **kw):
        s = ["SELECT table_name FROM v_catalog.views"]
        if schema is not None:
            s.append("WHERE table_schema = '%s'" % (schema,))
        s.append("ORDER BY table_schema, table_name")

        rs = connection.execute(' '.join(s))
        return [row[0] for row in rs]

    @reflection.cache
    def get_columns(self, connection, table_name, schema=None, **kw):
        schema_conditional = (
            "" if schema is None else "AND table_schema = '{schema}'".format(schema=schema))

        pk_column_select = """
        SELECT column_name FROM v_catalog.primary_keys
        WHERE table_name = '{table_name}'
        AND constraint_type = 'p'
        {schema_conditional}
        """.format(table_name=table_name, schema_conditional=schema_conditional)
        primary_key_columns = tuple(row[0] for row in connection.execute(pk_column_select))
        column_select = """
        SELECT
          column_name,
          data_type,
          column_default,
          is_nullable
        FROM v_catalog.columns
        where table_name = '{table_name}'
        {schema_conditional}
        UNION 
        SELECT
          column_name,
          data_type,
          '' as column_default,
          true as is_nullable
        FROM v_catalog.view_columns
        where table_name = '{table_name}'
        {schema_conditional}
        """.format(table_name=table_name, schema_conditional=schema_conditional)
        colobjs = []
        for row in connection.execute(column_select):
              colobj = self._get_column_info(
                  row.column_name, 
                  row.data_type, 
                  row.is_nullable,
                  row.column_default,
                  (row.column_name in primary_key_columns)
              )
              if colobj:
                  colobjs.append(colobj)
        return colobjs

    def _get_column_info(self, name, data_type, is_nullable, default, is_primary_key):
        m = re.match(r'(\w+)(?:\((\d+)(?:,(\d+))?\))?', data_type)
        if not m:
            raise ValueError("data type string not parseable for type name and optional parameters: %s" % data_type)
        typename = m.group(1).upper()
        typeobj = self.ischema_names[typename]
        typeargs = []
        typekwargs = {}
        for arg_group in (2, 3):
            try:
                param = m.group(arg_group)
                if param:
                    typeargs.append(int(param))
            except (TypeError, ValueError):
                pass

        if any(tz_string in typename for tz_string in ('TIMEZONE', 'TIME ZONE', 'TIMESTAMPTZ')):
            typekwargs['timezone'] = True

        if callable(typeobj):
            typeobj = typeobj(*typeargs, **typekwargs)

        return {
            'name': name,
            'type': typeobj,
            'nullable': is_nullable,
            'default': default,
            'primary_key': is_primary_key
        } 


    @reflection.cache
    def get_unique_constraints(self, connection, table_name, schema=None, **kw):

        query = None
        if schema is not None:
            query = "select constraint_id, constraint_name, column_name from v_catalog.constraint_columns \n\
            WHERE table_name = '" + table_name + "' AND table_schema = '" + schema + "'"
        else:
            query = "select constraint_id, constraint_name, column_name from v_catalog.constraint_columns \n\
            WHERE table_name = '" + table_name + "'"

        rs = connection.execute(query)

        unique_names = {row[1] for row in rs}

        result_dict = {unique: [] for unique in unique_names}
        for row in rs:
            result_dict[row[1]].append(row[2])

        result = []
        for key in result_dict.keys():
            result.append(
                {"name": key,
                 "column_names": result_dict[key]}
            )

        return result

    @reflection.cache
    def get_check_constraints(self, connection, table_name, schema=None, **kw):
        query = """
        SELECT
            cons.constraint_name as name,
            cons.predicate as src
        FROM
            v_catalog.table_constraints cons
        WHERE
            cons.constraint_type = 'c'
          AND
            cons.table_id = (
                SELECT
                    i.table_id
                FROM
                    v_catalog.tables i
                WHERE
                    i.table_name='{table_name}'
                {schema_clause}
            )
        """.format(table_name=table_name, schema_clause=(
            "" if schema is None else "AND i.table_schema ='{schema}'".format(schema=schema)))

        return [
            {
                'name': name,
                'sqltext': src[1:-1]
            } for name, src in connection.execute(query).fetchall()
        ]

    # constraints are enforced on selects, but returning nothing for these
    # methods allows table introspection to work

    def get_pk_constraint(self, bind, table_name, schema, **kw):
        return {'constrained_columns': [], 'name': 'undefined'}


    def get_foreign_keys(self, connection, table_name, schema, **kw):
        return []


    def get_indexes(self, connection, table_name, schema, **kw):
        return []


    # Disable index creation since that's not a thing in Vertica.
    def visit_create_index(self, create):
        return None
