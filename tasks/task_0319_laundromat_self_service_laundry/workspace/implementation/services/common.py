"""Shared request/validation/pagination helpers."""
from flask import request

from db import db, stamp_create, new_id
from errors import (
    err,
    ERR_VALIDATION,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_NO_ACTIVE_PLAN,
)
from response import now_iso


# ---- request body -----------------------------------------------------------
def get_body():
    """Parse JSON body; tolerate empty body as {} for action endpoints."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        # Body present but not valid JSON -> malformed request.
        raise err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Invalid value for {field}")


def require_int(value, field, *, minimum=None, maximum=None, gt=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if gt is not None and not value > gt:
        raise err(ERR_INVALID_REQUEST, f"{field} must be > {gt}")
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be <= {maximum}")
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return value


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return value


# ---- pagination (PRD §2.3) --------------------------------------------------
def parse_pagination():
    """limit defaults to 10, range [1,100]; offset defaults to 0, >= 0.

    Out-of-range -> ERR_VALIDATION (422).
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (tie-break by insertion seq), then slice."""
    ordered = sorted(items, key=lambda o: (o.get("created_at", ""), o.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# ---- existence (PRD §2.9) ---------------------------------------------------
def get_or_404(collection, resource_id, what):
    obj = collection.get(resource_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, f"{what} not found")
    return obj


# ---- shift lookup -----------------------------------------------------------
def open_shift_for(attendant_id):
    """The single OPEN Shift whose attendant_id == attendant_id, or None."""
    for s in db.shifts.values():
        if s["attendant_id"] == attendant_id and s["status"] == "OPEN":
            return s
    return None


# ---- active plan ------------------------------------------------------------
def active_plan():
    for p in db.pricing_plans.values():
        if p["status"] == "ACTIVE":
            return p
    return None


def require_active_plan():
    plan = active_plan()
    if plan is None:
        raise err(ERR_NO_ACTIVE_PLAN, "No ACTIVE pricing plan")
    return plan


# ---- loyalty ledger (append-only; PRD §2.4, §3.4) --------------------------
def write_ledger(member, entry_type, points_delta, vend_id):
    """Append an immutable LoyaltyLedgerEntry. balance_after reflects member's
    loyalty_points AFTER the delta has already been applied by the caller."""
    entry = {
        "member_id": member["id"],
        "vend_id": vend_id,
        "entry_type": entry_type,
        "points_delta": points_delta,
        "balance_after": member["loyalty_points"],
    }
    # LoyaltyLedgerEntry carries only id + created_at (no updated_at/version).
    stamp_create(entry, common_fields=False)
    db.loyalty_ledger[entry["id"]] = entry
    return entry
