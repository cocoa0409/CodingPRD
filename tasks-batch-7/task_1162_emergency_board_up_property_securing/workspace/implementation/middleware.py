"""Auth header extraction and role checking."""
from flask import request
from errors import err

RECOGNIZED_ROLES = {"PlatformAdmin", "Dispatcher", "Customer", "Subcontractor"}


def get_auth():
    """Extract X-User-ID / X-User-Role. Raise ERR_UNAUTHENTICATED on missing/unrecognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized role: %s" % role)
    return user_id, role


def require_role(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s not permitted" % role)
    return user_id, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_enum(value, allowed, field_name):
    if value not in allowed:
        raise err("ERR_INVALID_ENUM", "Invalid value for %s: %r" % (field_name, value))
    return value


def paginate_args():
    """Read limit/offset query params with defaults, min, max."""
    from errors import err as _err
    try:
        limit = request.args.get("limit", "10")
        limit = int(limit)
    except (TypeError, ValueError):
        raise _err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = request.args.get("offset", "0")
        offset = int(offset)
    except (TypeError, ValueError):
        raise _err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
