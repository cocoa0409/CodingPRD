"""Auth header extraction, role checking, body parsing (PRD §2.1, §2.8)."""
import functools

from flask import request

from constants import ROLES
from db import store
from errors import ApiError, ERR_AUTH, ERR_ROLE, bad_request


def get_body():
    """Return the JSON request body as a dict; anything else is ill-formed."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_AUTH, 400, "missing or invalid user context headers")
    if role == "Driver" and uid not in store.drivers:
        raise ApiError(ERR_AUTH, 400, "unknown driver identity")
    return uid, role


def require_roles(*roles):
    uid, role = get_auth()
    if role not in roles:
        raise ApiError(ERR_ROLE, 403, "role not permitted on this endpoint")
    return uid, role


ANY_ROLE = tuple(ROLES)


def locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with store.lock:
            return fn(*args, **kwargs)

    return wrapper


# ---- field validators (priority-3 well-formedness) ----

def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        bad_request(f"field '{field}' is required and must be a string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is not None and not isinstance(v, str):
        bad_request(f"field '{field}' must be a string")
    return v


def req_int(body, field):
    from util import is_int

    v = body.get(field)
    if v is None or not is_int(v):
        bad_request(f"field '{field}' is required and must be an integer")
    return v


def req_num(body, field):
    from util import is_num

    v = body.get(field)
    if v is None or not is_num(v):
        bad_request(f"field '{field}' is required and must be a number")
    return v


def req_enum(body, field, members):
    v = body.get(field)
    if v is None:
        bad_request(f"field '{field}' is required")
    if not isinstance(v, str) or v not in members:
        from errors import bad_enum

        bad_enum(f"field '{field}' must be one of {members}")
    return v


def req_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list):
        bad_request(f"field '{field}' is required and must be an array")
    return v
