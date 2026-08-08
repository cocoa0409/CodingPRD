"""Request payload validation helpers.

Distinguishes ERR_VALIDATION (missing / wrong-type / out-of-range, HTTP 400)
from ERR_INVALID_ENUM (well-formed string that is not a member of the declared
set, HTTP 422) — matching the priority ladder in PRD section 2.10.
"""

from flask import request

from clock import InvalidDateTime, parse_date, parse_datetime
from errors import ApiError


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def bad_enum(message):
    raise ApiError("ERR_INVALID_ENUM", message)


def json_body():
    """Return the parsed JSON body, or {} for an absent/empty body."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None or not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, min_len=1, max_len=None):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    return opt_string(body, name, min_len=min_len, max_len=max_len)


def opt_string(body, name, default=None, min_len=None, max_len=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def req_enum(body, name, allowed):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if value not in allowed:
        bad_enum("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if value not in allowed:
        bad_enum("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_enum_list(body, name, allowed):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' contains a non-string element." % name)
        if item not in allowed:
            bad_enum("Field '%s' contains an invalid value: %s." % (name, item))
    return list(value)


def _check_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    return value


def _bounds(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    value = _check_int(name, body[name])
    _bounds(name, value, minimum, maximum)
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    value = _check_int(name, body[name])
    _bounds(name, value, minimum, maximum)
    return value


def req_bool(body, name):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def req_datetime(body, name):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    try:
        return parse_datetime(body[name])
    except InvalidDateTime:
        bad("Field '%s' must be an ISO-8601 datetime." % name)


def req_date_str(body, name):
    """Validate a YYYY-MM-DD date but return the original string verbatim."""
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    try:
        parse_date(body[name])
    except InvalidDateTime:
        bad("Field '%s' must be a YYYY-MM-DD date." % name)
    return body[name]


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if str(limit) != raw.strip():
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if str(offset) != raw.strip():
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
