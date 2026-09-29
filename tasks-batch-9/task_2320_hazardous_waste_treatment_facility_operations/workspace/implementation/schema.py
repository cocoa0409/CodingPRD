"""Priority 4 request validation: bodies and query strings.

Unknown fields, wrong types, out-of-enum values and violated numeric bounds all
report ERR_INVALID_REQUEST.
"""

from flask import request

from errors import fail
from util import parse_date, parse_dt

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def raw_body():
    data = request.get_json(silent=True)
    if data is None:
        if request.get_data():
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_type(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    if kind in ("datetime", "date"):
        return isinstance(value, str)
    return True


def _coerce(name, value, rules):
    kind = rules.get("type", "string")
    if not _is_type(value, kind):
        fail("ERR_INVALID_REQUEST", "Field '%s' has the wrong type" % name)

    if kind == "datetime":
        parsed = parse_dt(value)
        if parsed is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid timestamp" % name)
        return parsed
    if kind == "date":
        parsed = parse_date(value)
        if parsed is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid date" % name)
        return parsed

    if kind == "string":
        if rules.get("non_empty") and not value.strip():
            fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty" % name)
        if "min_len" in rules and len(value) < rules["min_len"]:
            fail("ERR_INVALID_REQUEST", "Field '%s' is too short" % name)
        if "max_len" in rules and len(value) > rules["max_len"]:
            fail("ERR_INVALID_REQUEST", "Field '%s' is too long" % name)

    if "enum" in rules and value not in rules["enum"]:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not an accepted value" % name)

    if kind in ("int", "number"):
        if "ge" in rules and value < rules["ge"]:
            fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum" % name)
        if "gt" in rules and value <= rules["gt"]:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s" % (name, rules["gt"]))
        if "le" in rules and value > rules["le"]:
            fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum" % name)

    if kind == "array":
        if rules.get("non_empty") and len(value) == 0:
            fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty" % name)
        items = rules.get("items")
        if items is not None:
            out = []
            for element in value:
                if element is None:
                    fail("ERR_INVALID_REQUEST", "Field '%s' contains a null element" % name)
                out.append(_coerce(name + "[]", element, items))
            return out
        fields = rules.get("element_fields")
        if fields is not None:
            out = []
            for element in value:
                if not isinstance(element, dict):
                    fail("ERR_INVALID_REQUEST", "Field '%s' must contain objects" % name)
                out.append(validate(element, fields))
            return out
    return value


def validate(data, spec):
    for key in data.keys():
        if key not in spec:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'" % key)
    parsed = {}
    for name, rules in spec.items():
        present = name in data and data[name] is not None
        if not present:
            if rules.get("required"):
                fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
            if "default" in rules:
                parsed[name] = rules["default"]
            else:
                parsed[name] = None
            continue
        parsed[name] = _coerce(name, data[name], rules)
    return parsed


def body(spec):
    return validate(raw_body(), spec)


# ---------------------------------------------------------------------------
# query strings
# ---------------------------------------------------------------------------

def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of bounds" % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of bounds" % name)
    return value


def listing(filters=None, enums=None, extra=None):
    """Validate a list endpoint's query string.

    filters: accepted filter names. enums: name -> allowed values.
    Returns (filter values dict, limit, offset)."""
    filters = filters or []
    enums = enums or {}
    extra = extra or []
    allowed = set(filters) | set(extra) | {"limit", "offset"}
    for key in request.args.keys():
        if key not in allowed:
            fail("ERR_INVALID_REQUEST", "Unknown query parameter '%s'" % key)
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    values = {}
    for name in filters:
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        if name in enums and raw not in enums[name]:
            fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not an accepted value" % name)
        values[name] = raw
    return values, limit, offset


def required_int_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required" % name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer" % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
