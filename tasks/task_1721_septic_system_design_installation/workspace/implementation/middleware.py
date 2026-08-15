"""Auth header extraction, role checks, body parsing, and field validators."""

import json
from functools import wraps

from flask import g, request

import constants
import errors


def auth(*allowed_roles):
    """Priority 1-2: X-User-ID / X-User-Role presence, then role authorization."""
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or role is None or not uid.strip() or not role.strip():
                raise errors.ApiError(
                    errors.ERR_MISSING_AUTH, 401,
                    "X-User-ID and X-User-Role headers must be present and non-empty")
            if role not in constants.ALL_ROLES:
                raise errors.ApiError(
                    errors.ERR_FORBIDDEN, 403,
                    "Role named in X-User-Role is not recognized")
            if allowed_roles and role not in allowed_roles:
                raise errors.ApiError(
                    errors.ERR_FORBIDDEN, 403,
                    "Role {} is not permitted for this endpoint".format(role))
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return inner
    return deco


def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        try:
            data = json.loads(raw)
        except Exception:
            raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                                  "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "Request body must be a JSON object")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def req_str(b, field):
    val = b.get(field)
    if not isinstance(val, str) or not val:
        errors.invalid_request("Field '{}' is required and must be a non-empty string".format(field))
    return val


def opt_str(b, field):
    val = b.get(field)
    if val is None:
        return None
    if not isinstance(val, str):
        errors.invalid_request("Field '{}' must be a string".format(field))
    return val


def req_int(b, field):
    val = b.get(field)
    if not _is_int(val):
        errors.invalid_request("Field '{}' is required and must be an integer".format(field))
    return val


def opt_int(b, field):
    val = b.get(field)
    if val is None:
        return None
    if not _is_int(val):
        errors.invalid_request("Field '{}' must be an integer".format(field))
    return val


def req_num(b, field):
    val = b.get(field)
    if not _is_num(val):
        errors.invalid_request("Field '{}' is required and must be a number".format(field))
    return val


def req_bool(b, field):
    val = b.get(field)
    if not isinstance(val, bool):
        errors.invalid_request("Field '{}' is required and must be a boolean".format(field))
    return val


def req_enum(b, field, allowed):
    val = b.get(field)
    if not isinstance(val, str) or val not in allowed:
        errors.invalid_request(
            "Field '{}' must be one of {}".format(field, ", ".join(allowed)))
    return val


def req_note(b, field):
    """Narrative field with the 20-char minimum -> ERR_INSUFFICIENT_NOTE (priority 18)."""
    val = b.get(field)
    if not isinstance(val, str) or len(val) < constants.MIN_NOTE_LEN:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_NOTE, 400,
            "Field '{}' is required and must be at least {} characters".format(
                field, constants.MIN_NOTE_LEN))
    return val
