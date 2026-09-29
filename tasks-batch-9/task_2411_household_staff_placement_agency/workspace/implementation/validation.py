"""Request-shape validation helpers (PRD 2.11 step 2).

The six sub-steps run in this order and each helper below belongs to exactly
one of them:

  1. ERR_INVALID_REQUEST      absent / null required fields, string length
                              bounds, an email without an "@"
  2. ERR_INVALID_ENUM         a value outside its enumeration
  3. ERR_INVALID_RANGE        a numeric field outside its accepted band
  4. ERR_INVALID_DATE_FORMAT  a malformed date, timestamp or month key
  5. ERR_INVALID_INTERVAL     mis-ordered interval endpoints
  6. ERR_INVALID_LEDGER_AMOUNT a manual adjustment of exactly zero

Callers must invoke the helpers in that order so that the first failing rule
produces the response.
"""

from errors import fail
from response import object_response  # noqa: F401  (re-exported for convenience)
from timeutil import parse_date, parse_month, parse_timestamp

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_ACCEPTED_MAX = 200


def body_of(request):
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


# --------------------------------------------------------------------------
# step 2.1 -- ERR_INVALID_REQUEST
# --------------------------------------------------------------------------
def require_present(body, *names):
    for name in names:
        if name not in body or body[name] is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)


def require_string(body, name, min_len, max_len, required=True):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return None
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string" % name)
    if len(value) < min_len or len(value) > max_len:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be between %d and %d characters" % (name, min_len, max_len))
    return value


def require_email(body, name, min_len=1, max_len=254, required=True):
    value = require_string(body, name, min_len, max_len, required)
    if value is None:
        return None
    if "@" not in value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must contain an @" % name)
    return value


def require_bool(body, name, required=True, default=False):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % name)
    return value


def require_list(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return None
    value = body[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array" % name)
    return value


# --------------------------------------------------------------------------
# step 2.2 -- ERR_INVALID_ENUM
# --------------------------------------------------------------------------
def check_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_ENUM", "Field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def check_enum_list(values, name, allowed):
    for item in values:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_ENUM",
                 "Field '%s' may only contain %s" % (name, ", ".join(allowed)))
    return values


# --------------------------------------------------------------------------
# step 2.3 -- ERR_INVALID_RANGE
# --------------------------------------------------------------------------
def check_int(body, name, minimum=None, maximum=None, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_RANGE", "Field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_RANGE", "Field '%s' must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_RANGE", "Field '%s' must be at most %d" % (name, maximum))
    return value


def check_non_empty(values, name):
    if len(values) == 0:
        fail("ERR_INVALID_RANGE", "Field '%s' must not be empty" % name)
    return values


def range_fail(message):
    fail("ERR_INVALID_RANGE", message)


# --------------------------------------------------------------------------
# step 2.4 -- ERR_INVALID_DATE_FORMAT
# --------------------------------------------------------------------------
def check_date(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return None
    parsed = parse_date(body[name])
    if parsed is None:
        fail("ERR_INVALID_DATE_FORMAT", "Field '%s' must be a YYYY-MM-DD date" % name)
    return parsed


def check_timestamp(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return None
    parsed = parse_timestamp(body[name])
    if parsed is None:
        fail("ERR_INVALID_DATE_FORMAT",
             "Field '%s' must be an RFC 3339 UTC timestamp with a trailing Z" % name)
    return parsed


def check_month(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % name)
        return None
    parsed = parse_month(body[name])
    if parsed is None:
        fail("ERR_INVALID_DATE_FORMAT", "Field '%s' must be a YYYY-MM month key" % name)
    return parsed


# --------------------------------------------------------------------------
# step 2.5 -- ERR_INVALID_INTERVAL
# --------------------------------------------------------------------------
def interval_fail(message):
    fail("ERR_INVALID_INTERVAL", message)


# --------------------------------------------------------------------------
# Pagination and list filters (PRD 2.3)
# --------------------------------------------------------------------------
def list_params(request, enum_filters=None, plain_filters=()):
    """Validate list query parameters.

    Enumerated filters are checked first (ERR_INVALID_ENUM) and the pagination
    band second (ERR_INVALID_RANGE), matching the global ladder.
    """
    filters = {}
    if enum_filters:
        for name, allowed in enum_filters.items():
            raw = request.args.get(name)
            if raw is None:
                continue
            if raw not in allowed:
                fail("ERR_INVALID_ENUM",
                     "Filter '%s' must be one of %s" % (name, ", ".join(allowed)))
            filters[name] = raw
    for name in plain_filters:
        raw = request.args.get(name)
        if raw is not None:
            filters[name] = raw

    limit_raw = request.args.get("limit")
    if limit_raw is None or limit_raw == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_RANGE", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_ACCEPTED_MAX:
            fail("ERR_INVALID_RANGE",
                 "limit must be between %d and %d" % (PAGINATION_MIN_LIMIT, PAGINATION_ACCEPTED_MAX))

    offset_raw = request.args.get("offset")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_RANGE", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_RANGE", "offset must not be negative")

    # A limit above the permitted maximum but inside the accepted band serves
    # at most PAGINATION_MAX_LIMIT rows.
    effective_limit = min(limit, PAGINATION_MAX_LIMIT)
    return effective_limit, offset, filters


def apply_filters(rows, filters, field_map=None):
    field_map = field_map or {}
    result = rows
    for name, value in filters.items():
        field = field_map.get(name, name)
        result = [r for r in result if str(r.get(field)) == value]
    return result
