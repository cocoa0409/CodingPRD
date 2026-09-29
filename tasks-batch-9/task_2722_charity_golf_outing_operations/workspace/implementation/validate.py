"""Request schema validation — ladder tier 3 (PRD sections 2.3 / 2.5)."""

from flask import request

from envelope import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import fail
from store import is_iso_utc, canon_ts


def body():
    """Return the JSON body as a dict; a malformed body is a schema violation."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def only_fields(data, allowed):
    """Reject any body key the endpoint does not declare (computed/system writes)."""
    for key in data:
        if key not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' is not accepted by this endpoint." % key)


def require(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return data[name]


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_str(data, name, allow_empty=False):
    value = require(data, name)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def opt_str(data, name, default=None, allow_empty=True):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def req_enum(data, name, allowed):
    value = require(data, name)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_int(data, name, minimum=None, maximum=None):
    value = require(data, name)
    if not is_int(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    _range(name, value, minimum, maximum)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum, maximum)


def req_money(data, name):
    """A _cents field: integer, never negative."""
    return req_int(data, name, minimum=0)


def opt_money(data, name, default=0):
    return opt_int(data, name, default=default, minimum=0)


def req_signed_int(data, name):
    value = require(data, name)
    if not is_int(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def opt_signed_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_signed_int(data, name)


def req_number(data, name, minimum=None, maximum=None):
    value = require(data, name)
    if not is_num(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    _range(name, value, minimum, maximum)
    return float(value)


def opt_number(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return req_number(data, name, minimum, maximum)


def req_bool(data, name):
    value = require(data, name)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_bool(data, name)


def req_ts(data, name):
    value = require(data, name)
    if not is_iso_utc(value):
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be an ISO 8601 UTC timestamp ending in Z." % name)
    return canon_ts(value)


def opt_ts(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_ts(data, name)


def req_id_list(data, name):
    value = require(data, name)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    if len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain resource ids." % name)
    return value


def req_ref(data, name):
    value = require(data, name)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a resource id." % name)
    return value


def opt_ref(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_ref(data, name)


def _range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))


# --------------------------------------------------------------------------
# Query string helpers
# --------------------------------------------------------------------------
def page_params():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def q_str(name):
    return request.args.get(name)


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
