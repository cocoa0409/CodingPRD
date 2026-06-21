"""Shared helpers: entity scaffolding, validation primitives, lookups, pagination."""

from datetime import datetime, timezone

from flask import request

import db
import errors

# --- system constants ---------------------------------------------------------
DOC_FEE_CAP_CENTS = 100000          # documentation-fee cap (PRD 3.1)
WINTERIZE_FEE_CENTS = 25000         # flat winterization fee (PRD 3.10)

APR_BAND = {"PRIME": 599, "STANDARD": 899, "SUBPRIME": 1499}          # bps
MAX_LTV_BPS = {"PRIME": 13000, "STANDARD": 12000, "SUBPRIME": 11000}

CLASS_TYPES = {"CLASS_A", "CLASS_B", "CLASS_C", "TRAVEL_TRAILER", "FIFTH_WHEEL"}
CREDIT_TIERS = {"PRIME", "STANDARD", "SUBPRIME"}
ACQUISITIONS = {"STOCK", "CONSIGNMENT", "TRADE_IN"}

# Not-found error id per collection (for FK existence checks).
NOT_FOUND = {
    "dealerships": "ERR_DEALERSHIP_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "units": "ERR_UNIT_NOT_FOUND",
    "deals": "ERR_DEAL_NOT_FOUND",
    "service_bays": "ERR_SERVICE_BAY_NOT_FOUND",
    "service_orders": "ERR_SERVICE_ORDER_NOT_FOUND",
    "part_items": "ERR_PART_ITEM_NOT_FOUND",
    "warranty_plans": "ERR_WARRANTY_PLAN_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "storage_slots": "ERR_STORAGE_SLOT_NOT_FOUND",
    "recall_campaigns": "ERR_RECALL_CAMPAIGN_NOT_FOUND",
}


# --- entity scaffolding -------------------------------------------------------
def new_entity(extra):
    ts = db.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Bump version + updated_at on any mutation (PRD 2.4, 2.8)."""
    rec["version"] += 1
    rec["updated_at"] = db.now_iso()


# --- request body access ------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        errors.err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def invalid(msg="Invalid request."):
    errors.err("ERR_INVALID_REQUEST", msg)


# --- field validation primitives ---------------------------------------------
def require_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        invalid(f"Field '{name}' must be a non-empty string.")
    return v


def require_int(data, name, minimum=None, maximum=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid(f"Field '{name}' must be an integer.")
    if minimum is not None and v < minimum:
        invalid(f"Field '{name}' must be >= {minimum}.")
    if maximum is not None and v > maximum:
        invalid(f"Field '{name}' must be <= {maximum}.")
    return v


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data.get(name) is None:
        return default
    return require_int(data, name, minimum, maximum)


def require_number(data, name, minimum=None, exclusive_min=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid(f"Field '{name}' must be a number.")
    if minimum is not None and v < minimum:
        invalid(f"Field '{name}' must be >= {minimum}.")
    if exclusive_min is not None and v <= exclusive_min:
        invalid(f"Field '{name}' must be > {exclusive_min}.")
    return v


def require_bool(data, name, default=None):
    if name not in data or data.get(name) is None:
        if default is None:
            invalid(f"Field '{name}' is required.")
        return default
    v = data.get(name)
    if not isinstance(v, bool):
        invalid(f"Field '{name}' must be a boolean.")
    return v


def require_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        invalid(f"Field '{name}' must be one of {sorted(allowed)}.")
    return v


def opt_enum(data, name, allowed, default):
    if name not in data or data.get(name) is None:
        return default
    return require_enum(data, name, allowed)


# --- lookups ------------------------------------------------------------------
def get_or_404(collection, rec_id):
    if not isinstance(rec_id, str):
        errors.err(NOT_FOUND[collection])
    rec = db.store[collection].get(rec_id)
    if rec is None:
        errors.err(NOT_FOUND[collection])
    return rec


def find_dealership(did):
    return get_or_404("dealerships", did)


# --- datetime helpers ---------------------------------------------------------
def parse_iso(value, name="timestamp"):
    """Parse an ISO 8601 UTC timestamp; reject malformed input."""
    if not isinstance(value, str) or not value:
        invalid(f"Field '{name}' must be an ISO 8601 timestamp string.")
    txt = value
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        invalid(f"Field '{name}' is not a valid ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- pagination ---------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            invalid("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            invalid("offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at asc (PRD 2.3), filter on query params handled by caller."""
    limit, offset = pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
