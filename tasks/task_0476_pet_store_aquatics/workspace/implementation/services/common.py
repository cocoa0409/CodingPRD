"""Shared helpers: lookups, pagination, field validation, serialization."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from clock import parse_iso
from errors import err

# ---------------------------------------------------------------------------
# Lookups (PRD §2.5 — existence validated with the resource-specific not-found
# error). Collection -> not-found error id.
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "stores": "ERR_STORE_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "inventory_lots": "ERR_LOT_NOT_FOUND",
    "livestock_batches": "ERR_BATCH_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "prescriptions": "ERR_PRESCRIPTION_NOT_FOUND",
    "clinic_appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "special_orders": "ERR_SPECIAL_ORDER_NOT_FOUND",
    "recalls": "ERR_RECALL_NOT_FOUND",
    "adoption_events": "ERR_EVENT_NOT_FOUND",
    "adoption_placements": "ERR_PLACEMENT_NOT_FOUND",
}


def lookup(collection_name, resource_id):
    """Fetch a record by id from a named collection or raise its not-found error."""
    collection = getattr(db, collection_name)
    record = collection.get(resource_id)
    if record is None:
        raise err(_NOT_FOUND[collection_name])
    return record


# ---------------------------------------------------------------------------
# Body parsing & field validation (PRD §2.6, step 6 -> ERR_INVALID_FIELD_VALUE)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_FIELD_VALUE", "Request body must be a JSON object.")
    return body


def invalid(message="Invalid field value."):
    return err("ERR_INVALID_FIELD_VALUE", message)


def require_present(body, name):
    if name not in body or body[name] is None:
        raise invalid(f"Missing required field: {name}")
    return body[name]


def as_int(value, name):
    # Reject booleans (a subtype of int) and non-int types.
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(f"Field {name} must be an integer.")
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid(f"Field {name} must be a number.")
    return value


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        raise invalid(f"Field {name} must be a non-empty string.")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise invalid(f"Field {name} must be a boolean.")
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise invalid(f"Field {name} must be one of {sorted(allowed)}.")
    return value


def as_datetime(value, name):
    if not isinstance(value, str):
        raise invalid(f"Field {name} must be an ISO 8601 string.")
    try:
        return parse_iso(value)
    except Exception:
        raise invalid(f"Field {name} must be a valid ISO 8601 timestamp.")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
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
            raise invalid("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (PRD §2.3) and apply offset/limit."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Money: round half up to whole cents (PRD §2.8).
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a real number (int/float/Decimal) half-up to a whole integer."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Loyalty-tier discount fractions read at the relevant moment (PRD §3.4/§3.10/§3.11).
TIER_DISCOUNT = {"BRONZE": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
