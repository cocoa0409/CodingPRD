"""Shared helpers: auth context, common-field stamping, pagination, parsing.

PRD §2.1: every request must carry X-User-ID and X-User-Role. Roles are exactly
Customer, StoreManager, JudgeStaff. Missing header or unknown role ->
ERR_UNAUTHENTICATED (401). Well-formed but not permitted (or a Customer acting
on a resource it does not own) -> ERR_UNAUTHORIZED (403).
"""

from datetime import datetime, timezone

from flask import request

import db
from errors import err

ROLES = {"Customer", "StoreManager", "JudgeStaff"}


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """PRD §2.1 / validation priority 1: ERR_UNAUTHENTICATED before all else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return Auth(user_id, role)


def require_role(auth, allowed_roles):
    """PRD §2.1 / validation priority 2: role permission -> ERR_UNAUTHORIZED."""
    if auth.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def require_owner(auth, customer_id):
    """Customer ownership check (PRD §2.1). Operators (StoreManager/JudgeStaff)
    are opaque and never own-checked; only Customer is entity-backed."""
    if auth.role == "Customer" and auth.user_id != customer_id:
        raise err("ERR_UNAUTHORIZED", "Customer does not own this resource")


# ----------------------------------------------------------------------------
# Common-field lifecycle (PRD §2.5)
# ----------------------------------------------------------------------------

def stamp_create(entity):
    """Set id, created_at, updated_at, version on a freshly created entity."""
    ts = db.now_iso()
    entity["id"] = db.new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Every mutation (including derived-field recomputation) refreshes
    updated_at and increments version (PRD §2.5)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip private bookkeeping keys before serializing."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# Request body / field parsing
# ----------------------------------------------------------------------------

def get_body():
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return v


def require_enum(body, name, choices):
    v = body.get(name)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(choices)}")
    return v


def require_nonneg_int(body, name):
    v = require_int(body, name)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= 0")
    return v


def parse_datetime(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO 8601 string")
    dt = _parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a valid ISO 8601 timestamp")
    return dt


def _parse_iso(s):
    if not isinstance(s, str):
        return None
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Invalid pagination params fall back to defaults (clamped).
# ----------------------------------------------------------------------------

def parse_pagination():
    limit = _parse_int_arg("limit", 10)
    offset = _parse_int_arg("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items, limit, offset):
    """Sort by created_at ASC (PRD §2.3 default), apply limit/offset, return
    (page, total_count). Uses the creation sequence as the stable sort key."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
