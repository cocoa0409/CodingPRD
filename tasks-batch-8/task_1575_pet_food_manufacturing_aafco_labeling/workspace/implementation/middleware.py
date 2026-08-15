"""Auth middleware, RBAC, and common validation helpers."""

from flask import request
import errors

ROLES = {
    "PlatformAdmin",
    "FormulationScientist",
    "QAApprover",
    "QualityAnalyst",
    "TrialCoordinator",
    "ProductionPlanner",
    "LineOperator",
    "RegulatoryAffairs",
    "StateRegulator",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.unauthenticated()
    if not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id.strip(), role


def require_roles(*allowed):
    """Validate auth, then RBAC. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.unauthorized_role()
    return user_id, role


def get_json_body():
    """Return parsed JSON body as dict, or raise ERR_INVALID_REQUEST."""
    if not request.is_json:
        # Allow empty body for POST actions with no payload
        if request.content_length in (None, 0):
            return {}
        raise errors.invalid_request("Request body must be JSON")
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return body[name]


def optional_field(body, name, default=None):
    return body.get(name, default)


def require_string(body, name, max_len=None, non_empty=True):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {name} must be a string")
    if non_empty and not v.strip():
        raise errors.invalid_request(f"Field {name} must be non-empty")
    if max_len and len(v) > max_len:
        raise errors.invalid_request(f"Field {name} exceeds max length {max_len}")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if v not in allowed:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return v


def optional_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    return v


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return v


def parse_pagination():
    """Parse limit/offset query params per PRD 2.3. Returns (limit, offset)."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.pagination_error("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.pagination_error("limit outside [1,100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.pagination_error("offset must be an integer")
        if offset < 0:
            raise errors.pagination_error("offset < 0")
    return limit, offset


def paginate(items, limit, offset):
    """Return (page_items, total_count)."""
    total = len(items)
    page = items[offset: offset + limit]
    return page, total
