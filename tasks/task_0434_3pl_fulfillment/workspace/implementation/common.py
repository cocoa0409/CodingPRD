"""Shared route helpers: entity lookup with correct 404s, pagination, body parsing."""
from flask import request

from db import store
from errors import err

# Pagination defaults (PRD §2.3 / SCAFFOLD pagination_defaults).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


# ---- entity lookups (each maps to its own NOT_FOUND error per PRD §2.5) ----
def get_client(client_id):
    rec = store.clients.get(client_id)
    if rec is None:
        raise err("ERR_CLIENT_NOT_FOUND", "Client not found")
    return rec


def get_sku(sku_id):
    rec = store.skus.get(sku_id)
    if rec is None:
        raise err("ERR_SKU_NOT_FOUND", "SKU not found")
    return rec


def get_bin(bin_id):
    rec = store.bins.get(bin_id)
    if rec is None:
        raise err("ERR_BIN_NOT_FOUND", "Bin not found")
    return rec


def get_lot(lot_id):
    rec = store.inventory_lots.get(lot_id)
    if rec is None:
        raise err("ERR_LOT_NOT_FOUND", "Inventory lot not found")
    return rec


def get_receipt(receipt_id):
    rec = store.receipts.get(receipt_id)
    if rec is None:
        raise err("ERR_RECEIPT_NOT_FOUND", "Receipt not found")
    return rec


def get_order(order_id):
    rec = store.orders.get(order_id)
    if rec is None:
        raise err("ERR_ORDER_NOT_FOUND", "Order not found")
    return rec


def get_wave(wave_id):
    rec = store.waves.get(wave_id)
    if rec is None:
        raise err("ERR_WAVE_NOT_FOUND", "Wave not found")
    return rec


def get_pick_task(pick_task_id):
    rec = store.pick_tasks.get(pick_task_id)
    if rec is None:
        raise err("ERR_PICK_TASK_NOT_FOUND", "Pick task not found")
    return rec


def get_carton(carton_id):
    rec = store.cartons.get(carton_id)
    if rec is None:
        raise err("ERR_CARTON_NOT_FOUND", "Carton not found")
    return rec


def get_shipment(shipment_id):
    rec = store.shipments.get(shipment_id)
    if rec is None:
        raise err("ERR_SHIPMENT_NOT_FOUND", "Shipment not found")
    return rec


def get_return(return_id):
    rec = store.returns.get(return_id)
    if rec is None:
        raise err("ERR_RETURN_NOT_FOUND", "Return not found")
    return rec


def get_cycle_count(cycle_count_id):
    rec = store.cycle_counts.get(cycle_count_id)
    if rec is None:
        raise err("ERR_CYCLE_COUNT_NOT_FOUND", "Cycle count not found")
    return rec


def get_charge(charge_id):
    rec = store.billing_charges.get(charge_id)
    if rec is None:
        raise err("ERR_CHARGE_NOT_FOUND", "Billing charge not found")
    return rec


# ---- body parsing ----
def get_json_body():
    """Return the request JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object -> ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---- pagination ----
def parse_pagination():
    """Parse limit/offset query params with PRD §2.3 bounds.

    Out-of-range / non-integer values -> ERR_INVALID_REQUEST.
    Returns (limit, offset).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err("ERR_INVALID_REQUEST", "limit out of range")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (insertion sequence tiebreak), slice, build meta.

    Returns (page_items, pagination_meta).
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta
