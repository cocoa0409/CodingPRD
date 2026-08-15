"""Auth (pipeline stages 1-2), body/schema validation, and pagination helpers."""
from datetime import datetime, date, timezone

from flask import request

from errors import ApiError, raise_err
from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

ROLES = {"HRAdmin", "FinanceAdmin", "PayrollSpecialist", "Manager", "Employee", "VendorOps"}
ENTITY_BACKED_ROLES = {"Manager", "Employee"}
ALL_ROLES = ROLES


def auth_context():
    """Pipeline stage 1: user context headers present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID header missing or malformed")
    if not role or role not in ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-Role header missing or malformed")
    return user_id.strip(), role


def require_role(role, allowed):
    """Pipeline stage 2: role permitted for this endpoint."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_FOR_ROLE,
                  "Role %s is not permitted for this endpoint" % role)


def get_or_404(store, entity_id, label="Resource"):
    """Pipeline stage 3: path parameter / foreign key existence."""
    entity = store.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (label, entity_id))
    return entity


def body():
    """Parsed JSON object body; non-object or empty bodies become {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(b, key):
    v = b.get(key)
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Missing or invalid required field: %s" % key)
    return v


def opt_str(b, key, default=None):
    v = b.get(key, default)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Invalid field type: %s" % key)
    return v


def req_int(b, key):
    v = b.get(key)
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Missing or invalid required integer field: %s" % key)
    return v


def opt_int(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Invalid integer field: %s" % key)
    return v


def req_num(b, key):
    v = b.get(key)
    if not _is_num(v):
        raise_err(ERR_INVALID_REQUEST, "Missing or invalid required numeric field: %s" % key)
    return v


def opt_bool(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "Invalid boolean field: %s" % key)
    return v


def req_enum(b, key, members):
    v = b.get(key)
    if not isinstance(v, str) or v not in members:
        raise_err(ERR_INVALID_REQUEST,
                  "Missing or invalid enum field: %s (allowed: %s)"
                  % (key, ", ".join(sorted(members))))
    return v


def parse_iso_date(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Invalid date field: %s" % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Invalid ISO date for field: %s" % field)


def parse_iso_datetime(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Invalid datetime field: %s" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Invalid ISO datetime for field: %s" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """limit/offset with defaults limit=10 (min 1, max 100), offset=0.

    Out-of-range or malformed values are clamped to the documented bounds.
    """
    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _parse("limit", 10)
    offset = _parse("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
