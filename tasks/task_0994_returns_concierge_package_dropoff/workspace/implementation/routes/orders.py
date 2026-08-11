"""ReturnOrder, ReturnItem, Label, refund ledger and projection endpoints."""

from flask import Blueprint, request

import db
from db import store, stamp, touch
from errors import (
    ApiError, bad_request, invalid_state, already_terminal,
)
from services import (
    CONDITIONS, METHODS, LABEL_TYPES, LEDGER_WRITE_KINDS, ORDER_TERMINAL,
    OVERSIZE_CM, OVERAGE_HARD_CAP_MULTIPLIER,
    ser_order, ser_item, ser_label, ser_ledger_entry,
    get_or_404, order_items, order_labels, active_label, held_reservation,
    release_reservation, void_label, order_fall_back_to_initiated,
    merchant_plan, provisional_estimate, line_deduction_cents, issue_label,
    after_item_inspected, append_ledger, refund_projection, latest_final,
    open_cycle_covering, cycle_fulfilled, cycle_in_flight,
)
from util import (
    require_roles, respond, body, req_str, req_int, req_enum, req_number,
    opt_bool, req_field, paginate, is_int,
)

bp = Blueprint("orders", __name__)


# ----------------------------------------------------------- ownership -------
def check_order_access(uid, role, order):
    if role == "Shopper" and order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may act only on its own orders")
    if role == "MerchantAdmin" and order["merchant_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "MerchantAdmin may act only on its own merchant's orders")
    if role == "LocationOperator" and order.get("dropoff_location_id") != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")


def _order_terminal_check(order):
    if order["status"] in ORDER_TERMINAL:
        already_terminal("Order is in a terminal state")


def _method_dimension_feature_gates(order, plan, method, boxless):
    """Priority 8 (dimension) then 9 (feature gates), per PRD 2.8."""
    oversize = any(i["longest_side_cm"] > OVERSIZE_CM
                   for i in order_items(order["id"]))
    if method == "LOCKER_QR" and oversize:
        raise ApiError("ERR_DIM_EXCEEDS_XL", 422,
                       "Item longest_side_cm > 150 presented for a locker-based flow")
    if oversize and not plan["oversize_enabled"]:
        raise ApiError("ERR_OVERSIZE_NOT_SUPPORTED", 422,
                       "Plan lacks oversize_enabled but an oversize item was submitted")
    if method == "HOME_PICKUP" and not plan["pickup_enabled"]:
        raise ApiError("ERR_FEATURE_NOT_INCLUDED", 422,
                       "Plan lacks pickup_enabled")
    if boxless and not plan["boxless_enabled"]:
        raise ApiError("ERR_FEATURE_NOT_INCLUDED", 422,
                       "Plan lacks boxless_enabled")


# ------------------------------------------------------------- create --------
@bp.post("/return-orders")
def create_order():
    uid, role = require_roles("Shopper")
    b = body(required=True)
    shopper_id = req_str(b, "shopper_id")
    merchant_id = req_str(b, "merchant_id")
    method = req_enum(b, "method", METHODS)
    boxless = opt_bool(b, "boxless", False)
    items_in = req_field(b, "items")
    if not isinstance(items_in, list):
        bad_request("items must be an array")
    # Priority 3: ownership before deeper existence work.
    if shopper_id != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may create orders only for itself")
    # Priority 4: referenced ids exist, left to right; then item shape.
    shopper = get_or_404("shoppers", shopper_id)
    merchant = get_or_404("merchants", merchant_id)
    for line in items_in:
        if not isinstance(line, dict):
            bad_request("each item must be an object")
        req_str(line, "sku")
        qty = req_int(line, "quantity")
        if qty < 1:
            bad_request("quantity must be >= 1")
        price = req_int(line, "unit_price_cents")
        if price < 0:
            bad_request("unit_price_cents must be >= 0")
        req_enum(line, "declared_condition", CONDITIONS)
        req_number(line, "longest_side_cm", gt=0)
        w = req_int(line, "weight_grams")
        if w <= 0:
            bad_request("weight_grams must be > 0")
    # Priority 7: cross-entity referential integrity.
    if merchant["status"] != "ACTIVE":
        raise ApiError("ERR_MERCHANT_SUSPENDED", 409,
                       "Merchant is SUSPENDED (or CLOSED); new returns blocked")
    if shopper["status"] == "RESTRICTED":
        raise ApiError("ERR_SHOPPER_RESTRICTED", 403,
                       "Shopper is RESTRICTED; new returns blocked")
    cycle = open_cycle_covering(merchant_id, db.now())
    if cycle is None:
        raise ApiError("ERR_BILLING_CYCLE_NOT_OPEN", 409,
                       "No OPEN billing cycle covers the current clock")
    plan = merchant_plan(merchant)
    effective_boxless = True if method == "LOCKER_QR" else bool(boxless)
    # Priorities 8-9: dimension safety, then plan feature gates.
    oversize = any(l["longest_side_cm"] > OVERSIZE_CM for l in items_in)
    if method == "LOCKER_QR" and oversize:
        raise ApiError("ERR_DIM_EXCEEDS_XL", 422,
                       "Item longest_side_cm > 150 presented for a locker-based flow")
    if oversize and not plan["oversize_enabled"]:
        raise ApiError("ERR_OVERSIZE_NOT_SUPPORTED", 422,
                       "Plan lacks oversize_enabled but an oversize item was submitted")
    if method == "HOME_PICKUP" and not plan["pickup_enabled"]:
        raise ApiError("ERR_FEATURE_NOT_INCLUDED", 422,
                       "Plan lacks pickup_enabled")
    if effective_boxless and not plan["boxless_enabled"]:
        raise ApiError("ERR_FEATURE_NOT_INCLUDED", 422,
                       "Plan lacks boxless_enabled")
    # Priority 12: overage hard cap (projected == 2 * included is allowed).
    projected = len(cycle_fulfilled(cycle)) + len(cycle_in_flight(cycle)) + 1
    if projected > OVERAGE_HARD_CAP_MULTIPLIER * plan["included_returns"]:
        raise ApiError("ERR_OVERAGE_LIMIT_EXCEEDED", 422,
                       "Projected returns exceed the 2x included_returns hard cap")

    order = {
        "shopper_id": shopper_id,
        "merchant_id": merchant_id,
        "method": method,
        "boxless": effective_boxless,
        "status": "INITIATED",
        "refund_estimate_cents": 0,
        "refund_final_cents": None,
        "resolved_at": None,
        "tote_id": None,
        "dropoff_location_id": None,
        "total_units": 0,
        "total_weight_grams": 0,
        "has_oversize_item": False,
    }
    stamp(order)
    store["orders"][order["id"]] = order
    for line in items_in:
        item = {
            "return_order_id": order["id"],
            "sku": line["sku"],
            "quantity": line["quantity"],
            "unit_price_cents": line["unit_price_cents"],
            "declared_condition": line["declared_condition"],
            "condition": None,
            "longest_side_cm": line["longest_side_cm"],
            "weight_grams": line["weight_grams"],
            "status": "PENDING",
            "deduction_cents": None,
            "inspected_at": None,
        }
        stamp(item)
        store["items"][item["id"]] = item
    items = order_items(order["id"])
    order["total_units"] = sum(i["quantity"] for i in items)
    order["total_weight_grams"] = sum(i["weight_grams"] * i["quantity"] for i in items)
    order["has_oversize_item"] = any(i["longest_side_cm"] > OVERSIZE_CM for i in items)
    estimate = provisional_estimate(items, plan)
    order["refund_estimate_cents"] = estimate
    append_ledger(order["id"], "ESTIMATE", estimate,
                  "Provisional estimate at order creation", "system")
    return respond(ser_order(order), 201)


# ---------------------------------------------------------------- reads ------
@bp.get("/return-orders/<oid>")
def get_order(oid):
    uid, role = require_roles("Shopper", "MerchantAdmin", "SupportAgent",
                              "PlatformAdmin", "LocationOperator", "CarrierDispatcher")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    return respond(ser_order(order))


@bp.get("/return-orders/<oid>/items")
def list_items(oid):
    uid, role = require_roles("Shopper", "MerchantAdmin", "SupportAgent",
                              "PlatformAdmin", "LocationOperator")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    page, meta = paginate(order_items(oid))
    return respond([ser_item(i) for i in page], page=meta)


@bp.get("/return-items/<iid>")
def get_item(iid):
    uid, role = require_roles("Shopper", "MerchantAdmin", "SupportAgent",
                              "PlatformAdmin", "LocationOperator")
    item = get_or_404("items", iid)
    order = get_or_404("orders", item["return_order_id"])
    check_order_access(uid, role, order)
    return respond(ser_item(item))


# ---------------------------------------------------------------- cancel -----
@bp.post("/return-orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = require_roles("Shopper", "SupportAgent")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    _order_terminal_check(order)
    if order["status"] not in ("INITIATED", "LABEL_ISSUED"):
        invalid_state("Only INITIATED or LABEL_ISSUED orders can be cancelled")
    label = active_label(order)
    if label is not None:
        void_label(label)
    res = held_reservation(oid)
    if res is not None:
        release_reservation(res)
    order["status"] = "CANCELLED"
    touch(order)
    return respond(ser_order(order))


# ---------------------------------------------------------- method change ----
@bp.patch("/return-orders/<oid>/method")
def change_method(oid):
    uid, role = require_roles("Shopper")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    b = body(required=True)
    method = req_enum(b, "method", METHODS)
    boxless = opt_bool(b, "boxless", None)
    expected = req_field(b, "expected_return_order_version")
    if not is_int(expected):
        bad_request("expected_return_order_version must be an integer")
    # Priority 5: optimistic concurrency before state legality.
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_return_order_version does not match current version")
    _order_terminal_check(order)
    if order["status"] not in ("INITIATED", "LABEL_ISSUED"):
        invalid_state("Method can change only while INITIATED or LABEL_ISSUED")
    merchant = store["merchants"][order["merchant_id"]]
    plan = merchant_plan(merchant)
    new_boxless = boxless if boxless is not None else order["boxless"]
    if method == "LOCKER_QR":
        new_boxless = True
    _method_dimension_feature_gates(order, plan, method, new_boxless)
    label = active_label(order)
    if label is not None:
        void_label(label)
    res = held_reservation(oid)
    if res is not None:
        release_reservation(res)
    order["method"] = method
    order["boxless"] = new_boxless
    order["status"] = "INITIATED"
    touch(order)
    return respond(ser_order(order))


# ---------------------------------------------------------------- labels -----
@bp.post("/return-orders/<oid>/labels")
def issue_order_label(oid):
    uid, role = require_roles("Shopper")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    b = body(required=True)
    label_type = req_enum(b, "label_type", LABEL_TYPES)
    expected = req_field(b, "expected_return_order_version")
    if not is_int(expected):
        bad_request("expected_return_order_version must be an integer")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_return_order_version does not match current version")
    _order_terminal_check(order)
    if order["status"] not in ("INITIATED", "LABEL_ISSUED"):
        invalid_state("Labels can be issued only from INITIATED or LABEL_ISSUED")
    if not order_items(oid):
        invalid_state("Order has no return items")
    # Priority 9: QR_CODE forced for LOCKER_QR and boxless orders.
    if (order["method"] == "LOCKER_QR" or order["boxless"]) \
            and label_type != "QR_CODE":
        raise ApiError("ERR_LABEL_METHOD_MISMATCH", 422,
                       "label_type incompatible with method/boxless")
    prior = active_label(order)
    label = issue_label(order, label_type, supersedes=prior)
    if order["status"] == "INITIATED":
        order["status"] = "LABEL_ISSUED"
    touch(order)
    return respond(ser_label(label), 201)


@bp.get("/labels/<lid>")
def get_label(lid):
    uid, role = require_roles("Shopper", "SupportAgent", "PlatformAdmin",
                              "LocationOperator")
    label = get_or_404("labels", lid)
    order = get_or_404("orders", label["return_order_id"])
    check_order_access(uid, role, order)
    return respond(ser_label(label))


@bp.get("/labels")
def list_labels():
    uid, role = require_roles("Shopper", "SupportAgent", "PlatformAdmin")
    items = list(store["labels"].values())
    roid = request.args.get("return_order_id")
    supersedes = request.args.get("supersedes_label_id")
    status = request.args.get("status")
    if roid is not None:
        if role == "Shopper":
            order = get_or_404("orders", roid)
            check_order_access(uid, role, order)
        items = [l for l in items if l["return_order_id"] == roid]
    elif role == "Shopper":
        items = [l for l in items
                 if store["orders"][l["return_order_id"]]["shopper_id"] == uid]
    if supersedes is not None:
        items = [l for l in items if l["supersedes_label_id"] == supersedes]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, meta = paginate(items)
    return respond([ser_label(l) for l in page], page=meta)


@bp.post("/labels/<lid>/void")
def void_label_endpoint(lid):
    uid, role = require_roles("Shopper", "SupportAgent")
    label = get_or_404("labels", lid)
    order = get_or_404("orders", label["return_order_id"])
    check_order_access(uid, role, order)
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_NOT_ACTIVE", 409,
                       "Label action requires ISSUED status")
    void_label(label)
    res = None
    for r in store["reservations"].values():
        if r.get("label_id") == lid and r["status"] == "HELD":
            res = r
            break
    if res is not None:
        release_reservation(res)
    if order["status"] == "LABEL_ISSUED" and active_label(order) is None:
        order["status"] = "INITIATED"
        touch(order)
    return respond(ser_label(label))


# ------------------------------------------------------- drop-off / receive --
@bp.post("/return-orders/<oid>/confirm-dropoff")
def confirm_dropoff(oid):
    uid, role = require_roles("LocationOperator")
    order = get_or_404("orders", oid)
    b = body(required=True)
    location_id = req_str(b, "location_id")
    if uid != location_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Operator must own the confirmation location")
    location = get_or_404("locations", location_id)
    _order_terminal_check(order)
    if order["status"] != "LABEL_ISSUED":
        invalid_state("Only a LABEL_ISSUED order can be confirmed dropped off")
    if order["method"] != "COUNTER_DROP":
        invalid_state("Confirm-dropoff requires the COUNTER_DROP method")
    label = active_label(order)
    if label is not None and label["expires_at"] <= db.now():
        raise ApiError("ERR_LABEL_EXPIRED", 409,
                       "Confirm attempted with an expired label")
    if location["status"] != "OPERATIONAL":
        raise ApiError("ERR_LOCATION_NOT_OPERATIONAL", 409,
                       "Location is not OPERATIONAL")
    order["status"] = "DROPPED_OFF"
    order["dropoff_location_id"] = location_id
    touch(order)
    if label is not None:
        label["status"] = "CONSUMED"
        touch(label)
    return respond(ser_order(order))


@bp.post("/return-orders/<oid>/receive")
def receive_order(oid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator")
    order = get_or_404("orders", oid)
    if role == "LocationOperator" and order.get("dropoff_location_id") != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")
    _order_terminal_check(order)
    if order["status"] != "IN_TRANSIT":
        invalid_state("Only an IN_TRANSIT order can be received")
    order["status"] = "INSPECTING"
    touch(order)
    return respond(ser_order(order))


# -------------------------------------------------------------- inspection ---
@bp.post("/return-items/<iid>/inspect")
def inspect_item(iid):
    uid, role = require_roles("LocationOperator", "PlatformAdmin")
    item = get_or_404("items", iid)
    order = get_or_404("orders", item["return_order_id"])
    if role == "LocationOperator" and order.get("dropoff_location_id") != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")
    b = body(required=True)
    condition = req_enum(b, "condition", CONDITIONS)
    _order_terminal_check(order)
    if order["status"] not in ("INSPECTING", "EXCEPTION_PENDING"):
        invalid_state("Parent order must be INSPECTING or EXCEPTION_PENDING")
    if item["status"] == "INSPECTED":
        raise ApiError("ERR_ITEM_ALREADY_INSPECTED", 409,
                       "Item already INSPECTED")
    merchant = store["merchants"][order["merchant_id"]]
    plan = merchant_plan(merchant)
    item["condition"] = condition
    item["deduction_cents"] = line_deduction_cents(
        item["unit_price_cents"], item["quantity"], condition, plan,
        apply_waiver=True)
    item["inspected_at"] = db.now()
    item["status"] = "INSPECTED"
    touch(item)
    after_item_inspected(order, item)
    return respond(ser_item(item))


# ------------------------------------------------------- ledger / projection -
@bp.get("/return-orders/<oid>/refund-ledger")
def list_ledger(oid):
    uid, role = require_roles("Shopper", "MerchantAdmin", "SupportAgent",
                              "PlatformAdmin")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    entries = [e for e in store["ledger"].values() if e["return_order_id"] == oid]
    page, meta = paginate(entries)
    return respond([ser_ledger_entry(e) for e in page], page=meta)


@bp.post("/return-orders/<oid>/refund-ledger/entries")
def append_ledger_entry(oid):
    uid, role = require_roles("SupportAgent", "PlatformAdmin")
    order = get_or_404("orders", oid)
    b = body(required=True)
    kind = req_enum(b, "kind", ("ESTIMATE", "FINAL", "ADJUSTMENT", "CORRECTION"))
    if kind not in LEDGER_WRITE_KINDS:
        bad_request("ESTIMATE and FINAL entries are system-only")
    amount = req_int(b, "amount_cents")
    note = req_field(b, "note")
    if not isinstance(note, str):
        bad_request("note must be a string")
    # Priority 6: appends allowed only once the refund has posted.
    if order["status"] != "REFUND_POSTED":
        if order["status"] in ORDER_TERMINAL:
            already_terminal("Order has not posted a refund")
        invalid_state("Ledger appends require a REFUND_POSTED order")
    if kind == "CORRECTION" and role != "PlatformAdmin":
        raise ApiError("ERR_CORRECTION_REQUIRES_ADMIN", 403,
                       "CORRECTION entries are PlatformAdmin-only")
    projection = refund_projection(oid)
    if projection["payable_cents"] + amount < 0:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_PAYABLE", 422,
                       "Signed entry would drive payable_cents below 0")
    entry = append_ledger(oid, kind, amount, note, uid)
    return respond(ser_ledger_entry(entry), 201)


@bp.get("/return-orders/<oid>/refund-projection")
def get_projection(oid):
    uid, role = require_roles("Shopper", "MerchantAdmin", "SupportAgent",
                              "PlatformAdmin")
    order = get_or_404("orders", oid)
    check_order_access(uid, role, order)
    return respond(refund_projection(oid))
