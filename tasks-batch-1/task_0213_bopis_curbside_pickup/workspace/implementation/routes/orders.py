"""Order endpoints: CRUD, lines, and the fulfillment/payment state machine."""

from flask import Blueprint, request

from db import db, stamp_common, stamp_ledger, touch
from errors import err
from middleware import require_auth, get_json_body, get_identity
from response import object_response, array_response
from services.common import (
    require_str, require_pos_int, require_int, ref_or_404, get_or_404,
    parse_pagination, paginate,
    ser_order, ser_line, ser_pickup_event, ser_hold, ser_checkin,
)
from services import inventory as inv_svc
from services import money
from services.derived import recompute_slot_fill, hold_of
from services import order_ops
from clock import parse_iso, add_minutes

bp = Blueprint("orders", __name__)


# --- Ownership helper -------------------------------------------------------

def _check_owner(role, user_id, order):
    """Priority-3 ownership: a Customer acting on an order must own it."""
    if role == "Customer" and order["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "customer does not own this order")


# --- CRUD -------------------------------------------------------------------

@bp.post("/orders")
def create_order():
    user_id, role = require_auth({"Customer"})
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    store_id = require_str(body, "store_id")
    # ownership: the supplied customer_id must be the acting customer (priority 3)
    if customer_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "customer_id must match the acting customer")
    # FK existence (priority 5)
    ref_or_404(db.customers, customer_id, "customer")
    ref_or_404(db.stores, store_id, "store")

    rec = {
        "customer_id": customer_id,
        "store_id": store_id,
        "slot_id": None,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNAUTHORIZED",
        "authorized_total_cents": 0,
        "captured_total_cents": 0,
        "refunded_total_cents": 0,
        "verified": False,
    }
    stamp_common(rec)
    db.orders[rec["id"]] = rec
    return object_response(ser_order(rec), 201)


@bp.get("/orders")
def list_orders():
    require_auth({"StorePicker", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    limit, offset = parse_pagination(request.args)
    items = list(db.orders.values())
    for key in ("store_id", "slot_id", "customer_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    page, total = paginate(items, limit, offset)
    return array_response([ser_order(o) for o in page], limit, offset, total)


@bp.get("/orders/<oid>")
def get_order(oid):
    require_auth({"Customer", "StorePicker", "StoreAssociate",
                  "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.orders, oid)
    return object_response(ser_order(rec))


@bp.post("/orders/<oid>/lines")
def add_line(oid):
    user_id, role = require_auth({"Customer"})
    order = get_or_404(db.orders, oid)
    _check_owner(role, user_id, order)
    body = get_json_body()
    product_id = require_str(body, "product_id")
    qty_ordered = require_pos_int(body, "qty_ordered")
    ref_or_404(db.products, product_id, "product")
    # state guard: lines may only be added to a DRAFT order
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "lines may only be added to a DRAFT order")

    rec = {
        "order_id": oid,
        "product_id": product_id,
        "qty_ordered": qty_ordered,
        "qty_reserved": 0,
        "qty_picked": 0,
        "qty_handed_over": 0,
        "line_status": "PENDING",
    }
    stamp_common(rec)
    db.order_lines[rec["id"]] = rec
    return object_response(ser_line(rec), 201)


@bp.get("/orders/<oid>/lines")
def list_lines(oid):
    require_auth({"Customer", "StorePicker", "StoreAssociate",
                  "StoreManager", "PlatformAdmin"})
    get_or_404(db.orders, oid)
    limit, offset = parse_pagination(request.args)
    items = [ln for ln in db.order_lines.values() if ln["order_id"] == oid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_line(l) for l in page], limit, offset, total)


@bp.get("/orders/<oid>/pickup-events")
def list_order_events(oid):
    require_auth({"Customer", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    get_or_404(db.orders, oid)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.pickup_events.values() if e["order_id"] == oid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_pickup_event(e) for e in page], limit, offset, total)


@bp.get("/orders/<oid>/holds")
def list_order_holds(oid):
    require_auth({"Customer", "StorePicker", "StoreAssociate",
                  "StoreManager", "PlatformAdmin"})
    get_or_404(db.orders, oid)
    items = [h for h in db.holds.values() if h["order_id"] == oid]
    # no pagination params for this endpoint per scaffold (0 or 1)
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return array_response([ser_hold(h) for h in page], limit, offset, total)


@bp.get("/orders/<oid>/curbside-checkins")
def list_order_checkins(oid):
    require_auth({"Customer", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    get_or_404(db.orders, oid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.curbside_checkins.values() if c["order_id"] == oid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_checkin(c) for c in page], limit, offset, total)


# --- Transitions ------------------------------------------------------------

@bp.post("/orders/<oid>/submit")
def submit_order(oid):
    user_id, role = require_auth({"Customer"})
    order = get_or_404(db.orders, oid)
    _check_owner(role, user_id, order)
    body = get_json_body()
    slot_id = require_str(body, "slot_id")
    expected_slot_version = require_int(body, "expected_slot_version")
    # FK existence for slot (priority 5)
    slot = ref_or_404(db.pickup_slots, slot_id, "slot")

    lines = order_ops.lines_of(oid)

    # state guard (priority 8)
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "order is not DRAFT")
    # order must have >= 1 line (a structural precondition of the transition)
    if len(lines) < 1:
        raise err("ERR_INVALID_STATE", "order has no lines")

    # OCC slot version (priority 9)
    if expected_slot_version != slot["version"]:
        raise err("ERR_STALE_SLOT_VERSION",
                  "expected_slot_version does not match current slot version")

    # slot-store match (priority 10)
    if slot["store_id"] != order["store_id"]:
        raise err("ERR_SLOT_STORE_MISMATCH",
                  "slot belongs to a different store than the order")

    # cutoff (priority 12): clock < window_start - cutoff_offset_minutes
    now = db.clock.now()
    ws = parse_iso(slot["window_start"])
    cutoff_instant = add_minutes(ws, -slot["cutoff_offset_minutes"])
    if not (now < cutoff_instant):
        raise err("ERR_SLOT_CUTOFF_PASSED", "slot booking cutoff has passed")

    # customer not BLOCKED (priority 14)
    customer = db.customers.get(order["customer_id"])
    if customer is not None and customer["pickup_standing"] == "BLOCKED":
        raise err("ERR_CUSTOMER_BLOCKED", "customer is blocked from booking")

    # slot capacity (priority 21)
    if slot["booked_count"] >= slot["capacity"]:
        raise err("ERR_SLOT_FULL", "slot is full")

    # availability for every line (priority 22) — check ALL before committing
    line_inv = []
    for line in lines:
        inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
        avail = inv["available"] if inv is not None else 0
        if inv is None or avail < line["qty_ordered"]:
            raise err("ERR_INSUFFICIENT_AVAILABILITY",
                      "insufficient availability for a line")
        line_inv.append((line, inv))

    # --- commit ---
    reason = "ORDER:%s" % oid
    for line, inv in line_inv:
        inv_svc.reserve(inv, line["qty_ordered"], reason)
        line["qty_reserved"] = line["qty_ordered"]
        line["line_status"] = "RESERVED"
        touch(line)

    slot["booked_count"] += 1
    recompute_slot_fill(slot)
    touch(slot)

    order["slot_id"] = slot_id
    order["authorized_total_cents"] = money.authorized_total(order)
    order["payment_status"] = "AUTHORIZED"
    order["fulfillment_status"] = "SUBMITTED"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/start-picking")
def start_picking(oid):
    require_auth({"StorePicker"})
    order = get_or_404(db.orders, oid)
    if order["fulfillment_status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "order is not SUBMITTED")
    order["fulfillment_status"] = "PICKING"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/stage")
def stage_order(oid):
    require_auth({"StorePicker"})
    order = get_or_404(db.orders, oid)
    if order["fulfillment_status"] != "PICKING":
        raise err("ERR_INVALID_STATE", "order is not PICKING")
    lines = order_ops.lines_of(oid)
    terminal = {"PICKED", "SUBSTITUTED", "NOT_FULFILLED"}
    # every line terminal-for-staging AND at least one PICKED/SUBSTITUTED
    if any(ln["line_status"] not in terminal for ln in lines):
        raise err("ERR_STAGE_NOT_READY", "a line is not ready for staging")
    if not any(ln["line_status"] in {"PICKED", "SUBSTITUTED"} for ln in lines):
        raise err("ERR_STAGE_NOT_READY", "no fulfilled line to stage")
    order["fulfillment_status"] = "STAGED"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/ready")
def ready_order(oid):
    require_auth({"StorePicker"})
    order = get_or_404(db.orders, oid)
    if order["fulfillment_status"] != "STAGED":
        raise err("ERR_INVALID_STATE", "order is not STAGED")
    store = db.stores.get(order["store_id"])
    staged_at = db.clock.now()
    expires_at = add_minutes(staged_at, store["hold_window_minutes"])
    from clock import _fmt
    hold = {
        "order_id": oid,
        "store_id": order["store_id"],
        "staged_at": _fmt(staged_at),
        "expires_at": _fmt(expires_at),
        "hold_status": "ACTIVE",
    }
    stamp_common(hold)
    db.holds[hold["id"]] = hold
    order["fulfillment_status"] = "AWAITING_PICKUP"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/verify")
def verify_order(oid):
    require_auth({"StoreAssociate", "StoreManager"})
    order = get_or_404(db.orders, oid)
    body = get_json_body()
    require_str(body, "presented_name")
    require_str(body, "presented_phone")
    order["verified"] = True
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/pickup")
def pickup_order(oid):
    require_auth({"StoreAssociate"})
    order = get_or_404(db.orders, oid)
    body = get_json_body()

    # body well-formedness (priority 6) + handover reference (priority 5) come
    # before the state guard (8) and verified gate (17) per PRD §2.12.
    handovers = body.get("handovers")
    if not isinstance(handovers, list) or len(handovers) == 0:
        raise err("ERR_INVALID_REQUEST", "handovers must be a non-empty list")
    lines_by_id = {ln["id"]: ln for ln in order_ops.lines_of(oid)}
    parsed = []
    for h in handovers:
        if not isinstance(h, dict):
            raise err("ERR_INVALID_REQUEST", "each handover must be an object")
        line_id = h.get("order_line_id")
        if not isinstance(line_id, str) or not line_id:
            raise err("ERR_INVALID_REQUEST", "handover.order_line_id required")
        qty = h.get("qty_handed_over")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise err("ERR_INVALID_REQUEST",
                      "handover.qty_handed_over must be a positive integer")
        line = lines_by_id.get(line_id)
        if line is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "order line not found in this order")
        parsed.append((line, qty))

    # state guard (priority 8)
    if order["fulfillment_status"] != "AWAITING_PICKUP":
        raise err("ERR_INVALID_STATE", "order is not AWAITING_PICKUP")
    # verified requirement (priority 17)
    if not order["verified"]:
        raise err("ERR_ORDER_NOT_VERIFIED", "order is not verified")

    # per-line ceiling (priority 18): handover qty must not exceed qty_picked
    # consider cumulative when a line appears more than once
    cumulative = {}
    for line, qty in parsed:
        cumulative[line["id"]] = cumulative.get(line["id"], 0) + qty
    for line_id, total_qty in cumulative.items():
        line = lines_by_id[line_id]
        if line["qty_handed_over"] + total_qty > line["qty_picked"]:
            raise err("ERR_OVER_HANDOVER",
                      "handover exceeds qty_picked for a line")

    total_picked = sum(ln["qty_picked"] for ln in order_ops.lines_of(oid))
    total_handed_now = sum(qty for _, qty in parsed)

    # --- commit pickup events ---
    for line, qty in parsed:
        captured = money.captured_for_event(line, qty)
        ev = {
            "order_id": oid,
            "order_line_id": line["id"],
            "qty_handed_over": qty,
            "captured_cents": captured,
        }
        stamp_ledger(ev)
        db.pickup_events[ev["id"]] = ev
        line["qty_handed_over"] += qty

    # mark lines HANDED_OVER when fully handed
    for line in order_ops.lines_of(oid):
        if line["line_status"] in {"PICKED", "SUBSTITUTED"} and \
                line["qty_handed_over"] >= line["qty_picked"] and line["qty_picked"] > 0:
            line["line_status"] = "HANDED_OVER"
            touch(line)

    # overall handed-over total across the whole order
    overall_handed = sum(ln["qty_handed_over"] for ln in order_ops.lines_of(oid))

    order["captured_total_cents"] = money.captured_total(order)

    if overall_handed >= total_picked:
        # full pickup -> COMPLETED
        _complete_from_pickup(order)
    else:
        # partial -> PARTIALLY_PICKED_UP
        order["payment_status"] = "CAPTURED"
        order["fulfillment_status"] = "PARTIALLY_PICKED_UP"
    touch(order)
    return object_response(ser_order(order))


def _complete_from_pickup(order):
    """Full pickup completion side effects."""
    reason = "ORDER:%s" % order["id"]
    # release residual reservation on short/not-fulfilled lines
    for line in order_ops.lines_of(order["id"]):
        if line["qty_reserved"] > 0:
            inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
            if inv is not None:
                inv_svc.release(inv, line["qty_reserved"], reason)
            line["qty_reserved"] = 0
            touch(line)
    # COMPLETED refund = authorized - captured (PRD §3.9)
    order["refunded_total_cents"] = order["authorized_total_cents"] - order["captured_total_cents"]
    if order["refunded_total_cents"] == 0:
        order["payment_status"] = "CAPTURED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    hold = hold_of(db, order["id"])
    if hold is not None:
        hold["hold_status"] = "RELEASED"
        touch(hold)
    order_ops._slot_release(order, order["id"])
    order["fulfillment_status"] = "COMPLETED"


@bp.post("/orders/<oid>/close")
def close_order(oid):
    require_auth({"StoreAssociate", "StoreManager"})
    order = get_or_404(db.orders, oid)
    if order["fulfillment_status"] != "PARTIALLY_PICKED_UP":
        raise err("ERR_INVALID_STATE", "order is not PARTIALLY_PICKED_UP")
    reason = "ORDER:%s" % oid
    for line in order_ops.lines_of(oid):
        not_taken = line["qty_picked"] - line["qty_handed_over"]
        if not_taken > 0:
            # restock not-taken picked units (substitute product for SUBSTITUTED)
            if line["line_status"] == "SUBSTITUTED":
                sub = order_ops._accepted_sub(line)
                prod_id = sub["substitute_product_id"] if sub else line["product_id"]
            else:
                prod_id = line["product_id"]
            inv = inv_svc.find_inventory(order["store_id"], prod_id)
            if inv is not None:
                inv_svc.restock(inv, not_taken, reason)
        if line["qty_reserved"] > 0:
            inv2 = inv_svc.find_inventory(order["store_id"], line["product_id"])
            if inv2 is not None:
                inv_svc.release(inv2, line["qty_reserved"], reason)
            line["qty_reserved"] = 0
            touch(line)

    order["refunded_total_cents"] = order["authorized_total_cents"] - order["captured_total_cents"]
    if order["refunded_total_cents"] > 0:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    else:
        order["payment_status"] = "CAPTURED"
    hold = hold_of(db, oid)
    if hold is not None:
        hold["hold_status"] = "RELEASED"
        touch(hold)
    order_ops._slot_release(order, oid)
    order["fulfillment_status"] = "COMPLETED"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = require_auth({"Customer", "StoreManager"})
    order = get_or_404(db.orders, oid)
    status = order["fulfillment_status"]
    if role == "Customer":
        _check_owner(role, user_id, order)
        if status not in {"DRAFT", "SUBMITTED"}:
            raise err("ERR_INVALID_STATE",
                      "customer may cancel only DRAFT or SUBMITTED orders")
    else:  # StoreManager
        if status != "PICKING":
            raise err("ERR_INVALID_STATE",
                      "manager may cancel only a PICKING order")

    if status == "DRAFT":
        pass  # nothing reserved
    elif status == "SUBMITTED":
        order_ops.cancel_submitted(order)
    elif status == "PICKING":
        order_ops.cancel_picking(order)

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/orders/<oid>/expire")
def expire_order_endpoint(oid):
    require_auth({"StoreManager", "PlatformAdmin"})
    order = get_or_404(db.orders, oid)
    # state guard (priority 8)
    if order["fulfillment_status"] != "AWAITING_PICKUP":
        raise err("ERR_INVALID_STATE", "order is not AWAITING_PICKUP")
    # hold expirability (priority 13): clock >= expires_at (inclusive)
    hold = hold_of(db, oid)
    if hold is None:
        raise err("ERR_INVALID_STATE", "order has no active hold")
    now = db.clock.now()
    exp = parse_iso(hold["expires_at"])
    if not (now >= exp):
        raise err("ERR_HOLD_NOT_EXPIRABLE", "hold has not yet reached its deadline")
    order_ops.expire_order(order)
    return object_response(ser_order(order))
