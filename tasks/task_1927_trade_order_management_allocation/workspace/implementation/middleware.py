"""Auth (X-User-ID / X-User-Role), role gating, request body and pagination."""
import functools

from flask import request

from errors import raise_err

ROLES = {"Trader", "ExecutionDesk", "ComplianceOfficer", "SettlementOps", "DeskAdmin", "Auditor"}
ALL_ROLES = ("Trader", "ExecutionDesk", "ComplianceOfficer", "SettlementOps", "DeskAdmin", "Auditor")
AUDIT_READERS = ("ComplianceOfficer", "DeskAdmin", "Auditor")

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def actor():
    """(role, user_id) of the current request, after auth has passed."""
    return request.headers.get("X-User-Role"), request.headers.get("X-User-ID")


def require_roles(*roles):
    """Decorator: 401 when headers missing / role unrecognized, 403 when the
    recognized role is not on the endpoint's authorized list."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if not role or not user_id or role not in ROLES:
                raise_err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role / X-User-ID headers")
            if role not in roles:
                raise_err("ERR_FORBIDDEN", f"Role {role} is not authorized for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def body():
    """JSON request body as a dict; unparseable/absent body behaves as {}.
    Unknown fields are ignored by consumers (never rejected)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a non-empty string")
    return v


def optional_str(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string")
    return v


def require_int(b, field, minimum=None):
    v = b.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    return v


def require_enum(b, field, allowed):
    v = b.get(field)
    if v not in allowed:
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def pagination():
    """limit/offset query params: defaults 10/0, limit clamped to [1, 100],
    offset clamped to >= 0; non-integer input is a request-shape error."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else PAGE_DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else PAGE_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
    limit = max(PAGE_MIN_LIMIT, min(PAGE_MAX_LIMIT, limit))
    offset = max(PAGE_DEFAULT_OFFSET, offset)
    return limit, offset


def paged(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
