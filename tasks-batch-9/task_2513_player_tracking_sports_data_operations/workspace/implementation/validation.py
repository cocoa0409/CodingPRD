"""Body-schema and query-parameter validation (PRD §2.10 rank 4, PRD §2.3).

Rank 4 rejects: missing required field, wrong type, enum member outside the
declared set, an array declared non-empty that is empty, an out-of-range number,
and any unknown field.  ``segment_values`` on a normalization run is the one
deliberate exception: an empty array *passes* here so the domain refusal at
rank 38 survives to reach the caller.
"""

from flask import request

from errors import ApiError
from util import parse_dt

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def field(kind, required=True, default=None, values=None, minimum=None,
          maximum=None, exclusive_minimum=None, min_items=None, item=None):
    return {
        "kind": kind,
        "required": required,
        "default": default,
        "values": values,
        "minimum": minimum,
        "maximum": maximum,
        "exclusive_minimum": exclusive_minimum,
        "min_items": min_items,
        "item": item,
    }


def raw_body():
    """Return the parsed JSON body, or {} when absent/empty."""
    # parse_form_data=False keeps the raw bytes readable even when the client
    # omitted (or mis-stated) Content-Type; ``request.data`` would otherwise
    # hand the stream to the form parser and report an empty body.
    if not request.get_data(cache=True, parse_form_data=False):
        return {}
    # force=True so that a well-formed JSON body is honoured even when the
    # client omitted the Content-Type header.
    body = request.get_json(silent=True, force=True)
    if body is None:
        _bad("Request body is not valid JSON.")
    return body


def validate_body(spec):
    body = raw_body()
    if body is None:
        body = {}
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object.")

    for key in body:
        if key not in spec:
            _bad("Unknown field '%s' in request body." % key)

    out = {}
    for name, rules in spec.items():
        value = body.get(name, MISSING)
        if value is MISSING or value is None:
            if rules["required"]:
                _bad("Field '%s' is required." % name)
            out[name] = rules["default"]
            continue
        out[name] = _coerce(name, value, rules)
    return out


def _coerce(name, value, rules):
    kind = rules["kind"]
    if kind == "string":
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in rules["values"]:
            _bad("Field '%s' must be one of %s." % (name, ", ".join(rules["values"])))
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field '%s' must be an integer." % name)
        _check_range(name, value, rules)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad("Field '%s' must be a number." % name)
        _check_range(name, value, rules)
        return value
    if kind == "datetime":
        if not isinstance(value, str) or parse_dt(value) is None:
            _bad("Field '%s' must be an ISO 8601 timestamp." % name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            _bad("Field '%s' must be an array." % name)
        min_items = rules["min_items"]
        if min_items is not None and len(value) < min_items:
            _bad("Field '%s' must contain at least %d item(s)." % (name, min_items))
        item_rules = rules["item"]
        if item_rules is not None:
            return [_coerce("%s[%d]" % (name, i), v, item_rules)
                    for i, v in enumerate(value)]
        return list(value)
    _bad("Field '%s' has an unsupported type." % name)


def _check_range(name, value, rules):
    if rules["minimum"] is not None and value < rules["minimum"]:
        _bad("Field '%s' must be >= %s." % (name, rules["minimum"]))
    if rules["maximum"] is not None and value > rules["maximum"]:
        _bad("Field '%s' must be <= %s." % (name, rules["maximum"]))
    if rules["exclusive_minimum"] is not None and value <= rules["exclusive_minimum"]:
        _bad("Field '%s' must be > %s." % (name, rules["exclusive_minimum"]))


def no_body():
    """Acting endpoints that declare no input accept no fields at all.

    PRD §2.8 is explicit that unguarded mutations "must not be sent an
    expected-version input", so an unknown field on such an endpoint is a
    rank-4 schema violation like any other.
    """
    return validate_body({})


# --------------------------------------------------------------------------
# Query parameters
# --------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _bad("Query parameter '%s' must be an integer." % name)
    if raw.strip() != str(value):
        # rejects "1.0", " 1 " style values that int() would silently accept
        try:
            if int(raw.strip()) != value:
                _bad("Query parameter '%s' must be an integer." % name)
        except ValueError:
            _bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination():
    """PRD §2.3: limit default 10, min 1, max 100; offset default 0, min 0."""
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT,
                       PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET,
                        PAGINATION_MIN_OFFSET, None)
    return limit, offset


def string_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad("Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
