"""Auth, role authorisation, request-shape validation and pagination.

Check ordering follows PRD section 2.8; callers invoke these helpers in order.
"""

from flask import request

import db
from errors import ApiError


# ------------------------------------------------------------ 1 & 2: auth
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in db.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def auth(*allowed):
    """Steps 1 and 2 of the judging order."""
    user_id, role = authenticate()
    authorize(role, allowed)
    return user_id, role


# ------------------------------------------------------------ 3: path resolution
def resolve(store, key, error_id):
    rec = store.get(key)
    if rec is None:
        raise ApiError(error_id)
    return rec


# ------------------------------------------------------------ 5: request shape
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def req_string(data, field, allow_empty=False):
    value = data.get(field)
    if not isinstance(value, str):
        _bad("Field '{}' is required and must be a string.".format(field))
    if not allow_empty and value.strip() == "":
        _bad("Field '{}' must not be empty.".format(field))
    return value


def opt_string(data, field, default=None, nullable=True):
    if field not in data:
        return default
    value = data[field]
    if value is None:
        if nullable:
            return None
        _bad("Field '{}' must be a string.".format(field))
    if not isinstance(value, str):
        _bad("Field '{}' must be a string.".format(field))
    return value


def req_state_code(data, field):
    value = req_string(data, field)
    if len(value) != 2 or not value.isalpha() or not value.isupper():
        _bad("Field '{}' must be exactly two uppercase letters.".format(field))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if field not in data or not _is_int(value):
        _bad("Field '{}' is required and must be an integer.".format(field))
    if minimum is not None and value < minimum:
        _bad("Field '{}' must be >= {}.".format(field, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '{}' must be <= {}.".format(field, maximum))
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None, nullable=False):
    if field not in data:
        return default
    value = data[field]
    if value is None:
        if nullable:
            return None
        _bad("Field '{}' must be an integer.".format(field))
    if not _is_int(value):
        _bad("Field '{}' must be an integer.".format(field))
    if minimum is not None and value < minimum:
        _bad("Field '{}' must be >= {}.".format(field, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '{}' must be <= {}.".format(field, maximum))
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad("Field '{}' must be a boolean.".format(field))
    return value


def opt_number(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '{}' must be a number.".format(field))
    return value


def req_enum(data, field, members):
    value = req_string(data, field)
    if value not in members:
        _bad("Field '{}' must be one of {}.".format(field, sorted(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str) or value not in members:
        _bad("Field '{}' must be one of {}.".format(field, sorted(members)))
    return value


def req_datetime(data, field):
    value = data.get(field)
    if not isinstance(value, str):
        _bad("Field '{}' is required and must be an ISO-8601 instant.".format(field))
    parsed = db.parse_dt(value)
    if parsed is None:
        _bad("Field '{}' must be a valid ISO-8601 instant.".format(field))
    return parsed


# ------------------------------------------------------------ 5: pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            _bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            _bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        _bad("Query parameter '{}' must be one of {}.".format(name, sorted(members)))
    return value
