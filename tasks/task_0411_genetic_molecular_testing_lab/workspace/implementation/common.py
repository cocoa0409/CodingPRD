"""Auth, validation primitives, pagination, and shared helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err

VALID_ROLES = {
    "LabDirector",
    "LabIntake",
    "AccessioningTech",
    "MolecularTechnologist",
    "BillingSpecialist",
    "GeneticCounselor",
}

ALL_ROLES = sorted(VALID_ROLES)


def require_user_context():
    """Priority 1 (PRD 2.1): X-User-ID and X-User-Role present, role known.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            "Missing or invalid X-User-ID / X-User-Role headers.",
        )
    return user_id, role


def require_role(role, allowed_roles):
    """Priority 2 (PRD 2.1): role must be permitted for the operation."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role is not permitted for this operation.")


def get_json_body():
    """Parse JSON body; tolerate empty body as {}. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items):
    """Sort by created_at ASC (tie-break by id), apply limit/offset, return
    (page_items, pagination_meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Type / value validators -> ERR_INVALID_REQUEST (422)
# ---------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def require_non_negative_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-negative integer.")
    if v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-negative.")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def parse_iso(value, field):
    """Parse an ISO 8601 timestamp; return aware datetime. Bad -> ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string.")
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def require_iso(body, field):
    parse_iso(body.get(field), field)
    return body.get(field)
