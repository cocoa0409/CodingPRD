"""Request-shape validation helpers (PRD 2.3 / 2.8).

Everything in here raises ERR_INVALID_REQUEST (HTTP 400) except weight-class
ladder membership, which raises ERR_INVALID_WEIGHT_CLASS (HTTP 422).
"""

from flask import request

from errors import ApiError
from store import parse_date, parse_dt

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Return the JSON body as a dict.  A missing body is an empty dict."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        bad("Request body must be valid JSON.")
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def _present(body, field):
    return field in body and body[field] is not None


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def req_str(body, field, max_len=None, allow_empty=True):
    if field not in body or body[field] is None:
        bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must be non-empty." % field)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (field, max_len))
    return value


def opt_str(body, field, max_len=None, default=None, allow_empty=True):
    if not _present(body, field):
        if field in body and body[field] is None:
            return None
        return default
    return req_str(body, field, max_len=max_len, allow_empty=allow_empty)


def req_id_ref(body, field):
    """A body foreign key: must be present and a string before it is resolved."""
    if field not in body or body[field] is None:
        bad("Field '%s' is required." % field)
    if not isinstance(body[field], str) or body[field].strip() == "":
        bad("Field '%s' must be a resource id string." % field)
    return body[field]


def opt_id_ref(body, field):
    if not _present(body, field):
        return None
    if not isinstance(body[field], str) or body[field].strip() == "":
        bad("Field '%s' must be a resource id string." % field)
    return body[field]


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------

def _range_check(field, value, minimum, maximum, exclusive_min, exclusive_max):
    if minimum is not None:
        if exclusive_min and not value > minimum:
            bad("Field '%s' must be greater than %s." % (field, minimum))
        if not exclusive_min and value < minimum:
            bad("Field '%s' must be at least %s." % (field, minimum))
    if maximum is not None:
        if exclusive_max and not value < maximum:
            bad("Field '%s' must be less than %s." % (field, maximum))
        if not exclusive_max and value > maximum:
            bad("Field '%s' must be at most %s." % (field, maximum))
    return value


def req_num(body, field, minimum=None, maximum=None,
            exclusive_min=False, exclusive_max=False):
    if field not in body or body[field] is None:
        bad("Field '%s' is required." % field)
    value = body[field]
    if not is_number(value):
        bad("Field '%s' must be a number." % field)
    return _range_check(field, float(value), minimum, maximum,
                        exclusive_min, exclusive_max)


def opt_num(body, field, minimum=None, maximum=None, default=None,
            exclusive_min=False, exclusive_max=False):
    if not _present(body, field):
        return default
    return req_num(body, field, minimum, maximum, exclusive_min, exclusive_max)


def req_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        bad("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % field)
    return int(_range_check(field, int(value), minimum, maximum, False, False))


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if not _present(body, field):
        return default
    return req_int(body, field, minimum, maximum)


# --------------------------------------------------------------------------
# enums / dates
# --------------------------------------------------------------------------

def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    value = req_str(body, field)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date in YYYY-MM-DD form." % field)
    return parsed


def opt_date(body, field, default=None):
    if not _present(body, field):
        return default
    return req_date(body, field)


def req_datetime(body, field):
    value = req_str(body, field)
    parsed = parse_dt(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return value, parsed


# --------------------------------------------------------------------------
# weight-class ladder membership (PRD 2.5)
# --------------------------------------------------------------------------

def weight_class(body, field, season, required=True, default=None):
    if not _present(body, field):
        if required:
            bad("Field '%s' is required." % field)
        return default
    value = body[field]
    if not is_number(value):
        bad("Field '%s' must be a number." % field)
    ladder = season.get("weight_classes") or []
    for candidate in ladder:
        if float(candidate) == float(value):
            return int(candidate)
    raise ApiError(
        "ERR_INVALID_WEIGHT_CLASS",
        "Field '%s' is not a member of the season's weight_classes ladder." % field,
    )


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def window(rows, limit, offset):
    return rows[offset:offset + limit]
