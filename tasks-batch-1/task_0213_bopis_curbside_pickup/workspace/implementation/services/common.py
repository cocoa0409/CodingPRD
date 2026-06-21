"""Shared helpers: pagination, validation primitives, serialization projections."""

from errors import err
from db import db

# Pagination defaults (PRD §2.3 / scaffold response_envelope.pagination_defaults)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def parse_pagination(args):
    """Read limit/offset query params. Raises ERR_INVALID_REQUEST on bad values."""
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err("ERR_INVALID_REQUEST",
                      "limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if offset is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < OFFSET_MIN:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (oldest first), then page. Returns (page, total)."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --- Required-field / type helpers (ERR_INVALID_REQUEST) -------------------

def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v.strip() == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % name)
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return v


def require_pos_int(body, name):
    v = require_int(body, name)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a positive integer" % name)
    return v


def require_nonneg_int(body, name):
    v = require_int(body, name)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be >= 0" % name)
    return v


# --- Existence helpers -----------------------------------------------------

def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "resource not found: %s" % _id)
    return rec


def ref_or_404(collection, _id, label="reference"):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "%s not found: %s" % (label, _id))
    return rec


# --- Serialization projections ---------------------------------------------
# Each entity exposes exactly the fields the PRD/scaffold declare, in a stable order.

COMMON_TAIL = ["created_at", "updated_at", "version"]
LEDGER_TAIL = ["created_at"]


def _project(rec, fields):
    return {f: rec.get(f) for f in fields}


def ser_customer(rec):
    return _project(rec, ["id", "email", "full_name", "phone",
                          "no_show_strikes", "pickup_standing"] + COMMON_TAIL)


def ser_store(rec):
    return _project(rec, ["id", "name", "state_code", "curbside_spaces",
                          "hold_window_minutes", "active_curbside_count"] + COMMON_TAIL)


def ser_product(rec):
    return _project(rec, ["id", "sku", "name", "unit_price_cents",
                          "substitution_group"] + COMMON_TAIL)


def ser_inventory(rec):
    return _project(rec, ["id", "store_id", "product_id", "on_hand",
                          "reserved", "available"] + COMMON_TAIL)


def ser_slot(rec):
    return _project(rec, ["id", "store_id", "window_start", "window_end",
                          "cutoff_offset_minutes", "capacity", "booked_count",
                          "fill_status"] + COMMON_TAIL)


def ser_order(rec):
    return _project(rec, ["id", "customer_id", "store_id", "slot_id",
                          "fulfillment_status", "payment_status",
                          "authorized_total_cents", "captured_total_cents",
                          "refunded_total_cents", "verified"] + COMMON_TAIL)


def ser_line(rec):
    return _project(rec, ["id", "order_id", "product_id", "qty_ordered",
                          "qty_reserved", "qty_picked", "qty_handed_over",
                          "line_status"] + COMMON_TAIL)


def ser_substitution(rec):
    return _project(rec, ["id", "order_line_id", "substitute_product_id",
                          "substitute_qty", "decision_status",
                          "price_delta_cents"] + COMMON_TAIL)


def ser_hold(rec):
    return _project(rec, ["id", "order_id", "store_id", "staged_at",
                          "expires_at", "hold_status"] + COMMON_TAIL)


def ser_checkin(rec):
    return _project(rec, ["id", "order_id", "store_id", "vehicle_description",
                          "checkin_status"] + COMMON_TAIL)


def ser_pickup_event(rec):
    return _project(rec, ["id", "order_id", "order_line_id", "qty_handed_over",
                          "captured_cents"] + LEDGER_TAIL)


def ser_movement(rec):
    return _project(rec, ["id", "store_inventory_id", "movement_type",
                          "delta_on_hand", "delta_reserved", "reason"] + LEDGER_TAIL)
