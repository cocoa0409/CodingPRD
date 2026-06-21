"""Shared request helpers used by all route modules.

Kept separate from app.py to avoid circular imports.
"""
from datetime import datetime, timezone
from flask import request

from db import db
from errors import err
from middleware import get_identity, require_role
from util import round2, parse_iso_date


# ---------------------------------------------------------------------------
# Request body / pagination helpers
# ---------------------------------------------------------------------------
def body():
    """Parsed JSON body as a dict ({} when absent). Malformed JSON => 422."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def pagination():
    """limit default 10, min 1, max 100; offset default 0 (PRD §2.3)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    rows = sorted(rows, key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def server_today():
    """Server 'today' as a date, honoring the pinned test clock (PRD §3.10)."""
    if db.clock_iso:
        return parse_iso_date(db.clock_iso)
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Lookup / auth helpers
# ---------------------------------------------------------------------------
def find(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return rec


def auth(allowed_roles):
    """Priority 1 (auth) then priority 2 (role). Returns (user_id, role)."""
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role


# ---------------------------------------------------------------------------
# Field validation helpers (all raise ERR_INVALID_REQUEST / p21)
# ---------------------------------------------------------------------------
def require_fields(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % f)


def as_enum(data, field, allowed, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % field)
        return None
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "invalid value for %s" % field)
    return v


def as_number(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % field)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return v


def as_int(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % field)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def as_str(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % field)
        return None
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return v


def as_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return v


# ---------------------------------------------------------------------------
# Liability recompute helpers
# ---------------------------------------------------------------------------
def recompute_wallet_liability(fest):
    total = 0.0
    for w in db.wristbands.values():
        if w["festival_id"] == fest["id"] and w["lifecycle_status"] == "ACTIVE":
            total += w["balance"]
    fest["total_wallet_liability"] = round2(total)


def recompute_refund_liability(fest):
    total = 0.0
    for r in db.refunds.values():
        if r["festival_id"] == fest["id"] and r["status"] == "ISSUED":
            total += r["amount"]
    fest["total_refund_liability"] = round2(total)
