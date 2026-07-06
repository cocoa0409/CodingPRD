"""Auth, validation, pagination, calc helpers shared by routes."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err
from constants import ROLES
from clock import parse_iso


# --------------------------------------------------------------------------- #
# Auth / RBAC (PRD §2.1, §2.7)
# --------------------------------------------------------------------------- #
def auth(allowed_roles):
    """Validate auth headers and role membership. Returns (user_id, role).

    Priority 1: both headers present, else ERR_UNAUTHENTICATED.
    Priority 2: role permitted, else ERR_UNAUTHORIZED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in ROLES or role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s not permitted for this operation" % role)
    return user_id, role


# --------------------------------------------------------------------------- #
# Body parsing / field validation (PRD §2.7 priorities 5-7)
# --------------------------------------------------------------------------- #
def body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return data
    return {}


def require_str(data, name):
    if name not in data or data[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    v = data[name]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return v


def require_int(data, name):
    if name not in data or data[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    return v


def require_number(data, name):
    if name not in data or data[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    return v


def require_enum(data, name, domain):
    v = require_str(data, name)
    if v not in domain:
        raise err("ERR_INVALID_ENUM", "Field %s out of domain" % name)
    return v


def require_datetime(data, name):
    v = require_str(data, name)
    try:
        return parse_iso(v)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Field %s must be ISO 8601" % name)


def optional_enum(data, name, domain, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
    if v not in domain:
        raise err("ERR_INVALID_ENUM", "Field %s out of domain" % name)
    return v


# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------- #
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_LIMIT", "limit must be an integer 1..100")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_LIMIT", "limit must be within 1..100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer >= 0")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #
def rhu_int(value):
    """Round half up to a whole integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(value):
    """Round half up to 2 decimal places, returned as float."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hours_between(start_dt, end_dt):
    """Elapsed hours as a Decimal."""
    delta = end_dt - start_dt
    return Decimal(delta.total_seconds()) / Decimal(3600)
