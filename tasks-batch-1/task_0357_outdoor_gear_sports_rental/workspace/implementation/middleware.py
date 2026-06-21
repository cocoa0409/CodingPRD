"""Auth header extraction + common request-parsing helpers.

Auth headers per PRD §2.1: X-User-ID and X-User-Role.
Roles: ShopAdmin, RentalAgent, Renter (spelled precisely).
"""
from datetime import datetime, timezone
from flask import request
import errors

VALID_ROLES = {"ShopAdmin", "RentalAgent", "Renter"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/invalid.

    Validation priority places ERR_VALIDATION (payload well-formedness) before
    auth; callers that need that ordering parse the body first. Auth itself
    requires both headers present with a recognized role value.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise errors.unauthorized()


def get_json_body():
    """Return the parsed JSON body as a dict (or {} when absent)."""
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Treat an empty/missing body as an empty object; required-field checks
        # downstream produce ERR_VALIDATION where a field is mandatory.
        return {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0. Out-of-range or
    non-integer values are malformed -> ERR_VALIDATION."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def parse_dt(value, field):
    """Parse an ISO 8601 datetime into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.validation(f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.validation(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.validation(f"Missing required field: {f}")


def require_str(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"{field} must be a non-empty string")
    return v


def require_int(body, field, min_value=None):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise errors.validation(f"{field} must be >= {min_value}")
    return v


def optional_int(body, field, default, min_value=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, min_value=min_value)


def require_enum(body, field, allowed):
    require_fields(body, [field])
    v = body[field]
    if v not in allowed:
        raise errors.validation(f"{field} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.validation(f"{field} must be a boolean")
    return v
