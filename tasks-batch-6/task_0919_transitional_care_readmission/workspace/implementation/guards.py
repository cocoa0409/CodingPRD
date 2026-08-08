"""Ladder rungs 1-9 helpers: auth, RBAC, body validation, enums, existence,
link mismatch, episode ownership and the global write gate.
"""
from flask import request

import constants as C
import store
from errors import ApiError


# ---------------------------------------------------------------- rung 1 / 2
def authenticate():
    """Rung 1. Both headers present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed_roles):
    """Rung 2. The supplied role appears in the endpoint's authorised list."""
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def auth(allowed_roles):
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


# ------------------------------------------------------------------- rung 3
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return data


def _bad(field, reason):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, reason))


def req_string(data, field, allow_empty=False):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and value == "":
        _bad(field, "must be non-empty")
    return value


def opt_string(data, field, default=None, allow_empty=True):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and value == "":
        _bad(field, "must be non-empty")
    return value


def _check_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s" % maximum)
    return value


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    return _check_int(field, data[field], minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return _check_int(field, data[field], minimum, maximum)


def _check_number(field, value, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    if exclusive_min is not None and not value > exclusive_min:
        _bad(field, "must be greater than %s" % exclusive_min)
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s" % maximum)
    return value


def opt_number(data, field, default=None, minimum=None, maximum=None, exclusive_min=None):
    if field not in data or data[field] is None:
        return default
    return _check_number(field, data[field], minimum, maximum, exclusive_min)


def req_bool(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    if not isinstance(data[field], bool):
        _bad(field, "must be a boolean")
    return data[field]


def req_array(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    if not isinstance(data[field], list):
        _bad(field, "must be an array")
    return data[field]


def req_date(data, field):
    raw = req_string(data, field)
    value = store.parse_date(raw)
    if value is None:
        _bad(field, "must be a YYYY-MM-DD calendar date")
    return raw


def req_instant(data, field):
    raw = req_string(data, field)
    value = store.parse_instant(raw)
    if value is None:
        _bad(field, "must be an ISO 8601 UTC instant")
    return value


# ------------------------------------------------------------------- rung 4
def enum(value, members, field):
    """Rung 4. Membership of a body field named in PRD 2.10 rung 4."""
    if value not in members:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "Field '%s' must be one of %s." % (field, ", ".join(members)),
        )
    return value


def enum_members(values, members, field):
    for value in values:
        if not isinstance(value, str) or value not in members:
            raise ApiError(
                "ERR_INVALID_ENUM",
                "Every member of '%s' must be one of %s." % (field, ", ".join(members)),
            )
    return values


def validation_enum(value, members, field):
    """A closed-set body field NOT named in rung 4 - membership is a rung 3 failure."""
    if value not in members:
        _bad(field, "must be one of %s" % ", ".join(members))
    return value


# --------------------------------------------------------------- rung 5 / 6
def get_episode(episode_id):
    row = store.DB["episodes"].get(episode_id)
    if row is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    return row


def get_row(table, row_id):
    row = store.DB[table].get(row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


# ------------------------------------------------------------------- rung 8
def require_episode_owner(episode, user_id, role):
    """Rung 8. A CareNavigator may only act on the episodes assigned to them."""
    if role == "CareNavigator" and episode["navigator_id"] != user_id:
        raise ApiError("ERR_NOT_EPISODE_OWNER")


# ------------------------------------------------------------------- rung 9
def require_open_records(episode):
    """Rung 9. The global write gate."""
    if episode["record_posture"] != "OPEN":
        raise ApiError("ERR_EPISODE_RECORDS_FROZEN")


# ---------------------------------------------------------------- pagination
def pagination():
    limit = C.PAGE_LIMIT_DEFAULT
    offset = C.PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if str(raw_limit).strip() != str(limit):
            _bad("limit", "must be an integer")
        if limit < C.PAGE_LIMIT_MIN or limit > C.PAGE_LIMIT_MAX:
            _bad("limit", "must be between %d and %d" % (C.PAGE_LIMIT_MIN, C.PAGE_LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if str(raw_offset).strip() != str(offset):
            _bad("offset", "must be an integer")
        if offset < C.PAGE_OFFSET_DEFAULT:
            _bad("offset", "must be at least 0")
    return limit, offset


def filters(*names):
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None:
            out[name] = value
    return out


def bool_filter(value):
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None
