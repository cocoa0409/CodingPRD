"""Authentication, endpoint authorisation and request body shape helpers.

Validation precedence (PRD §2.9):
  1. authentication        -> ERR_UNAUTHENTICATED   (401)
  2. endpoint authorisation-> ERR_ROLE_NOT_PERMITTED (403)
  3. Parent ownership      -> ERR_NOT_CONSENT_HOLDER (403)
  ... path ids, body FKs, coherence, OCC, body shape, ...
"""
from functools import wraps

from flask import g, request

from constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE
from errors import fail


def authenticate(*allowed_roles):
    """Steps 1 and 2 of PRD §2.9."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(HEADER_USER_ID)
            role = request.headers.get(HEADER_USER_ROLE)
            if not user_id or not role or role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED")
            g.user_id = user_id
            g.role = role
            if allowed_roles and role not in allowed_roles:
                fail("ERR_ROLE_NOT_PERMITTED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def body():
    """Parsed JSON body; a missing or non-object body behaves as an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


# --- body shape helpers (PRD §2.9 step 8) ---------------------------------


def req_string(data, key, allow_empty=False):
    value = data.get(key)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % key)
    return value


def opt_string(data, key, default=None, allow_empty=True):
    if key not in data or data.get(key) is None:
        return default
    return req_string(data, key, allow_empty=allow_empty)


def req_enum(data, key, allowed):
    value = data.get(key)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data.get(key) is None:
        return default
    return req_enum(data, key, allowed)


def req_bool(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def opt_bool(data, key, default=None):
    if key not in data or data.get(key) is None:
        return default
    return req_bool(data, key)


def req_int(data, key):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    return value


def opt_int(data, key, default=None):
    if key not in data or data.get(key) is None:
        return default
    return req_int(data, key)


def req_enum_list(data, key, allowed, non_empty=True):
    value = data.get(key)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % key)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail(
                "ERR_INVALID_REQUEST",
                "%s entries must be one of %s." % (key, ", ".join(allowed)),
            )
    return value


def opt_enum_list(data, key, allowed, default=None):
    if key not in data or data.get(key) is None:
        return list(default) if default is not None else []
    return req_enum_list(data, key, allowed, non_empty=False)


def req_string_list(data, key, non_empty=False):
    value = data.get(key)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % key)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % key)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "%s entries must be strings." % key)
    return value


def opt_string_list(data, key, default=None):
    if key not in data or data.get(key) is None:
        return list(default) if default is not None else []
    return req_string_list(data, key)


def req_datetime(data, key):
    from timeutil import parse_iso

    value = data.get(key)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime string." % key)
    parsed = parse_iso(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a valid ISO 8601 datetime." % key)
    return parsed
