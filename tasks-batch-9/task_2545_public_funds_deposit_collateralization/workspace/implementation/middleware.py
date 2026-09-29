"""Authentication, role authorisation, request-shape and pagination helpers.

The rejection ladder of PRD 2.7 is enforced by calling these helpers in the
ladder's order from each route handler: authenticate, authorise the role, check
entity-backed ownership, resolve existence, then validate request shape.
"""

from flask import request

import db
from constants import ALL_ROLES, DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import fail


# --- rung 1 + 2 ---------------------------------------------------------------
def authorize(*roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    if roles and role not in roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return user_id.strip(), role


# --- rung 4 -------------------------------------------------------------------
def resolve(collection, record_id):
    record = db.get(collection, record_id)
    if record is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return record


def resolve_fk(collection, value):
    """Resolve a body foreign key. A value that is absent or not a string is a
    request-shape problem, deferred to rung 5."""
    if not isinstance(value, str) or not value.strip():
        return None
    record = db.get(collection, value)
    if record is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return record


# --- rung 5 -------------------------------------------------------------------
def body_json():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST")
    return payload


def present(body, field):
    return field in body and body[field] is not None


def req_id(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST")
    return value


def opt_id(body, field):
    if not present(body, field):
        return None
    return req_id(body, field)


def req_text(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST")
    return value


def opt_text(body, field, default=None):
    if not present(body, field):
        return default
    return req_text(body, field)


def opt_bool(body, field, default=None):
    if not present(body, field):
        return default
    value = body.get(field)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST")
    return value


def req_enum(body, field, allowed):
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST")
    return value


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    return req_enum(body, field, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, field, allow_zero=False, minimum=None, maximum=None):
    value = body.get(field)
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST")
    _check_int_bounds(value, allow_zero, minimum, maximum)
    return value


def opt_int(body, field, default=None, allow_zero=False, minimum=None, maximum=None):
    if not present(body, field):
        return default
    return req_int(body, field, allow_zero=allow_zero, minimum=minimum, maximum=maximum)


def _check_int_bounds(value, allow_zero, minimum, maximum):
    if allow_zero:
        if value < 0:
            fail("ERR_INVALID_REQUEST")
    elif value <= 0:
        fail("ERR_INVALID_REQUEST")
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST")
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST")


def req_version(body, field):
    """A version pin is a plain integer; a mismatching value is a rung-6
    concern, not a rung-5 one."""
    value = body.get(field)
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST")
    return value


def req_ts(body, field):
    value = body.get(field)
    stamp = db.Ts.of(value) if isinstance(value, str) else None
    if stamp is None:
        fail("ERR_INVALID_REQUEST")
    return stamp


def opt_ts(body, field, default=None):
    if not present(body, field):
        return default
    return req_ts(body, field)


# --- pagination + filters (PRD 2.3) -------------------------------------------
def page_params():
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int(raw_limit)
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            fail("ERR_INVALID_REQUEST")
    if raw_offset is not None:
        offset = _query_int(raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST")
    return limit, offset


def _query_int(raw):
    text = raw.strip()
    if not text:
        fail("ERR_INVALID_REQUEST")
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST")
    return int(text)


def query_filter(name, allowed=None):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST")
    return value


def paginate(records, limit, offset):
    return records[offset:offset + limit]
