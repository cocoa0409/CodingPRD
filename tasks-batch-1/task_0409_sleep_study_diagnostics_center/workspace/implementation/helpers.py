"""Shared request helpers: auth, RBAC, pagination, body validation, time math.

Header names, role names, pagination params, and error ids are read straight
from PRD §2.1 / §2.3 / §2.7 and SCAFFOLD §1.4 / §1.7.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

# The five roles, spelled precisely per PRD §2.1.
VALID_ROLES = {
    "SchedulingCoordinator",
    "SleepTechnologist",
    "Physician",
    "DMECoordinator",
    "Patient",
}


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validations priority 1 & 2)
# ---------------------------------------------------------------------------
def require_auth():
    """Validate X-User-ID and X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)


# ---------------------------------------------------------------------------
# Body parsing / validation (priority 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % field)


def require_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)


def require_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)


def require_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)


def require_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10 min 1 max 100; offset default 0 min 0;
# out-of-bounds -> ERR_PAGINATION_INVALID)
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit out of range [1,100]")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sort_by_creation(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places):
    """Round to `places` decimal places using ROUND_HALF_UP; returns float."""
    q = Decimal(1).scaleb(-places)  # e.g. places=1 -> Decimal('0.1')
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_iso(value, field="timestamp"):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse an ISO date YYYY-MM-DD (or the date portion of a datetime)."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO date string" % field)
    s = value.strip()
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid ISO date" % field)


def epoch_ms(dt):
    return dt.timestamp() * 1000.0
