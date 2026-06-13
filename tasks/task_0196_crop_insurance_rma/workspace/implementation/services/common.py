"""Shared helpers: entity scaffolding, pagination, primitive validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors


# ---- System-managed common fields (PRD §2.4) --------------------------------
def make_common():
    """id/created_at/updated_at/version for resources WITH common fields."""
    ts = db.now_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def make_identity_common():
    """id/created_at only — for Producer and Agent (PRD §2.4)."""
    return {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.4 / §2.5)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip internal-only keys (those starting with _) for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---- Rounding ---------------------------------------------------------------
def round_half_up_int(value):
    """Round a numeric value to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round to 2 decimal places, half-up. Returns a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---- Pagination (PRD §2.3) --------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params. limit default 10, min 1, max 100;
    offset default 0. Malformed values -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable via _seq), then slice."""
    ordered = sorted(items, key=lambda e: e.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(e) for e in page], total


# ---- Primitive field validation (ERR_INVALID_REQUEST, priority 4) -----------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def as_number(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be numeric" % name)
    return v


def as_int(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    return v


def as_string(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return None
    v = body[name]
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a string" % name)
    return v


def as_enum(body, name, allowed, required=True):
    v = as_string(body, name, required)
    if v is None:
        return None
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be one of %s" % (name, sorted(allowed)))
    return v


# ---- Datetime parsing -------------------------------------------------------
def parse_datetime(body, name, required=True):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Returns None when absent and not required. Bad format -> ERR_INVALID_REQUEST."""
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return None
    v = body[name]
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % name)
    return parse_iso(v, name)


# ---- Existence resolution (ERR_NOT_FOUND, priority 3) -----------------------
def lookup(collection, entity_id):
    """Return the entity or raise ERR_NOT_FOUND."""
    if entity_id is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    e = collection.get(entity_id)
    if e is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return e


def parse_iso(v, name="datetime"):
    s = v
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s is not a valid ISO 8601 datetime" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
