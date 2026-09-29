"""Authentication, RBAC and request-body helpers (PRD §2.1, §2.3, §2.10)."""

from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "StateAdmin",
    "ComplianceReviewer",
    "AgencyCoordinator",
    "StateWarehouseOperator",
)

ANY_ROLE = ROLES


def authenticate(allowed_roles):
    """Validation positions 1 and 2 of PRD §2.10."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    return user_id, role


def endpoint(*allowed_roles):
    """Decorator wiring the auth/RBAC gate ahead of the handler body."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate(allowed_roles)
            g.user_id = user_id
            g.role = role
            return func(*args, **kwargs)

        return wrapper

    return decorator


def open_endpoint(func):
    """Decorator for the one endpoint that needs no headers (PRD §2.4)."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        g.user_id = request.headers.get("X-User-ID")
        g.role = request.headers.get("X-User-Role")
        return func(*args, **kwargs)

    return wrapper


def body():
    """Parsed JSON object body; a malformed body is ERR_INVALID_REQUEST."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    payload = request.get_json(silent=True, force=True)
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return payload


def pagination():
    """limit/offset per PRD §2.3 — defaults 10/0, limit 1..100, offset >= 0."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def query_filter(name, allowed=None):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value
