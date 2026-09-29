"""Order intake, point-of-sale injection, kitchen readiness and dispatch."""
from flask import Blueprint

import clock
import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import domain, serializers
from services.money import apply_bps

bp = Blueprint("orders", __name__)


def _slot_held(order):
    """True when the order currently holds one of the store's prep slots."""
    return (order["injection_status"] in K.SLOT_HOLDING_INJECTION
            and order["fulfillment_status"] == "PREPARING")


# ------------------------------------------------------------ place order ----
@bp.post("/orders")
@M.endpoint(M.CHANNEL_PARTNER)
def create_order():
    payload = validation.body()
    store_id = validation.req_str(payload, "store_id")
    channel_id = validation.req_str(payload, "channel_id")
    external_ref = validation.req_str(payload, "external_ref")
    mode = validation.req_enum(payload, "fulfillment_mode", K.FULFILLMENT_MODES)
    lines = validation.req_lines(payload)
    tip = validation.opt_int(payload, "tip_cents", 0, default=0)

    store = common.get_store(store_id)
    channel = common.get_channel(channel_id)
    M.require_channel_scope(channel["id"])

    for existing in db.orders.values():
        if (existing["channel_id"] == channel["id"]
                and existing["external_ref"] == external_ref):
            fail(errors.ERR_DUPLICATE_EXTERNAL_REF)

    if store["active_menu_version_id"] is None:
        fail(errors.ERR_STORE_MENU_NOT_PUBLISHED)
    if domain.store_open_window(store) is None:
        fail(errors.ERR_STORE_CLOSED)
    if store["throttle_state"] == "PAUSED":
        fail(errors.ERR_STORE_PAUSED)
    if mode == "DELIVERY" and not channel["accepts_delivery"]:
        fail(errors.ERR_CHANNEL_DELIVERY_UNSUPPORTED)

    resolved = []
    for entry in lines:
        listing = domain.listing_for(store["id"], channel["id"], entry["sku"])
        if listing is None:
            fail(errors.ERR_SKU_NOT_LISTED)
        resolved.append((entry, listing))
    for _entry, listing in resolved:
        if listing["availability_state"] != "AVAILABLE":
            fail(errors.ERR_ITEM_NOT_AVAILABLE)
    if mode == "DELIVERY":
        for _entry, listing in resolved:
            item = db.menu_items.get(listing["menu_item_id"])
            if item is None or not item["is_delivery_eligible"]:
                fail(errors.ERR_ITEM_NOT_DELIVERY_ELIGIBLE)

    bucket_index = domain.bucket_index_for(store)
    if domain.bucket_load(store, bucket_index) >= store["prep_capacity_per_bucket"]:
        fail(errors.ERR_CAPACITY_BUCKET_FULL)

    created_at = clock.now()
    quote = domain.compute_quote(store, mode, "CONFIRMED", at=created_at,
                                before=created_at)
    if quote["total_minutes"] > K.MAX_QUOTE_MINUTES:
        fail(errors.ERR_QUOTE_WINDOW_EXCEEDED)

    order = db.record()
    order.update({
        "store_id": store["id"],
        "channel_id": channel["id"],
        "menu_version_id": store["active_menu_version_id"],
        "remittance_statement_id": None,
        "external_ref": external_ref,
        "fulfillment_mode": mode,
        "tip_cents": tip,
        "subtotal_cents": 0,
        "markup_cents": 0,
        "tax_cents": 0,
        "service_fee_cents": channel["service_fee_cents"],
        "commission_cents": 0,
        "channel_collected_cents": 0,
        "brand_net_cents": 0,
        "refunded_total_cents": 0,
        "bucket_index": bucket_index,
        "promised_ready_at": quote["ready_at"],
        "injection_status": "PENDING",
        "injection_attempt_count": 0,
        "fulfillment_status": "PREPARING",
        "settlement_status": "SETTLEABLE",
    })
    db.orders[order["id"]] = order

    stored_lines = []
    for entry, listing in resolved:
        item = db.menu_items.get(listing["menu_item_id"])
        tax_bps = item["tax_bps"] if item is not None else 0
        subtotal = listing["price_cents"] * entry["quantity"]
        line = db.record(journal=True)
        line.update({
            "order_id": order["id"],
            "sku": entry["sku"],
            "quantity": entry["quantity"],
            "base_price_cents": listing["base_price_cents"],
            "unit_price_cents": listing["price_cents"],
            "tax_bps": tax_bps,
            "line_subtotal_cents": subtotal,
            "line_tax_cents": apply_bps(subtotal, tax_bps),
        })
        db.order_lines[line["id"]] = line
        stored_lines.append(line)

    domain.compute_order_totals(order, stored_lines, channel)

    store["open_order_count"] += 1
    store["reserved_prep_slots"] += 1
    db.touch(store)
    return response.object_response(serializers.order(order), 201)


@bp.get("/orders/<order_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def read_order(order_id):
    order = common.get_order(order_id)
    M.require_order_scope(order)
    return response.object_response(serializers.order(order))


@bp.get("/orders")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def list_orders():
    limit, offset = validation.pagination()
    store_id = validation.query_str("store_id")
    channel_id = validation.query_str("channel_id")
    menu_version_id = validation.query_str("menu_version_id")
    statement_id = validation.query_str("remittance_statement_id")
    settlement_status = validation.query_enum("settlement_status", K.SETTLEMENT_STATUSES)
    injection_status = validation.query_enum("injection_status", K.INJECTION_STATUSES)
    fulfillment_status = validation.query_enum("fulfillment_status",
                                               K.FULFILLMENT_STATUSES)

    def keep(rec):
        if store_id is not None and rec["store_id"] != store_id:
            return False
        if channel_id is not None and rec["channel_id"] != channel_id:
            return False
        if menu_version_id is not None and rec["menu_version_id"] != menu_version_id:
            return False
        if statement_id is not None and rec["remittance_statement_id"] != statement_id:
            return False
        if settlement_status is not None and rec["settlement_status"] != settlement_status:
            return False
        if injection_status is not None and rec["injection_status"] != injection_status:
            return False
        if fulfillment_status is not None and rec["fulfillment_status"] != fulfillment_status:
            return False
        return True

    records = db.sorted_records(db.orders, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.order(r) for r in page], meta)


@bp.get("/orders/<order_id>/lines")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def list_order_lines(order_id):
    limit, offset = validation.pagination()
    order = common.get_order(order_id)
    M.require_order_scope(order)
    records = domain.lines_of_order(order["id"])
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.order_line(r) for r in page], meta)


# ------------------------------------------------------- POS injection ------
@bp.post("/orders/<order_id>/inject")
@M.endpoint(M.STORE_OPERATOR)
def inject_order(order_id):
    payload = validation.body()
    result_code = validation.req_enum(payload, "pos_result_code", K.POS_RESULT_CODES)
    order = common.get_order(order_id)
    M.require_store_scope(order["store_id"])

    if order["injection_status"] not in ("PENDING", "TABLET_FALLBACK"):
        fail(errors.ERR_INVALID_INJECTION_STATE)

    store = db.stores.get(order["store_id"])
    previous_status = order["injection_status"]
    order["injection_attempt_count"] += 1
    attempt_count = order["injection_attempt_count"]

    attempt = db.record(journal=True)
    attempt.update({
        "order_id": order["id"],
        "attempt_number": attempt_count,
        "pos_result_code": result_code,
        "outcome": "ACCEPTED" if result_code == "OK" else "REJECTED",
        "attempted_at": clock.now(),
    })
    db.injection_attempts[attempt["id"]] = attempt

    if result_code == "OK":
        order["injection_status"] = "ACCEPTED"
        if previous_status == "TABLET_FALLBACK":
            store["tablet_backlog_count"] = max(0, store["tablet_backlog_count"] - 1)
            db.touch(store)
    elif previous_status == "PENDING":
        if attempt_count >= store["pos_retry_limit"]:
            if store["tablet_backlog_count"] < store["tablet_backlog_threshold"]:
                order["injection_status"] = "TABLET_FALLBACK"
                store["tablet_backlog_count"] += 1
                db.touch(store)
            else:
                order["injection_status"] = "FAILED"
                order["fulfillment_status"] = "CANCELLED"
                store["reserved_prep_slots"] = max(0, store["reserved_prep_slots"] - 1)
                store["open_order_count"] = max(0, store["open_order_count"] - 1)
                db.touch(store)
                domain.withdraw_open_assignments(order)

    db.touch(order)
    return response.object_response(serializers.order(order))


@bp.get("/orders/<order_id>/injection-attempts")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR)
def list_injection_attempts(order_id):
    limit, offset = validation.pagination()
    order = common.get_order(order_id)
    M.require_store_scope(order["store_id"])
    records = db.sorted_records(db.injection_attempts,
                                lambda a: a["order_id"] == order["id"])
    page, meta = response.paginate(records, limit, offset)
    return response.array_response(
        [serializers.injection_attempt(r) for r in page], meta)


@bp.post("/orders/<order_id>/resume-injection")
@M.endpoint(M.STORE_OPERATOR)
def resume_injection(order_id):
    order = common.get_order(order_id)
    M.require_store_scope(order["store_id"])
    store = db.stores.get(order["store_id"])

    if store["throttle_state"] == "PAUSED":
        fail(errors.ERR_STORE_PAUSED)
    if domain.bucket_load(store, order["bucket_index"], exclude_order_id=order["id"]) \
            >= store["prep_capacity_per_bucket"]:
        fail(errors.ERR_CAPACITY_BUCKET_FULL)
    if order["injection_status"] != "INJECTION_HELD":
        fail(errors.ERR_INVALID_INJECTION_STATE)
    for line in domain.lines_of_order(order["id"]):
        listing = domain.listing_for(order["store_id"], order["channel_id"], line["sku"])
        if listing is None or listing["availability_state"] != "AVAILABLE":
            fail(errors.ERR_ITEM_STILL_UNAVAILABLE)

    order["injection_status"] = "PENDING"
    db.touch(order)
    store["reserved_prep_slots"] += 1
    db.touch(store)
    return response.object_response(serializers.order(order))


# ------------------------------------------------------------- readiness ----
@bp.post("/orders/<order_id>/ready")
@M.endpoint(M.STORE_OPERATOR)
def ready_order(order_id):
    order = common.get_order(order_id)
    M.require_store_scope(order["store_id"])

    if order["fulfillment_status"] != "PREPARING":
        fail(errors.ERR_INVALID_ORDER_STATE)
    if order["injection_status"] not in ("ACCEPTED", "TABLET_FALLBACK"):
        fail(errors.ERR_ORDER_NOT_INJECTED)

    order["fulfillment_status"] = "READY"
    db.touch(order)
    store = db.stores.get(order["store_id"])
    store["reserved_prep_slots"] = max(0, store["reserved_prep_slots"] - 1)
    db.touch(store)
    return response.object_response(serializers.order(order))


@bp.post("/orders/<order_id>/cancel")
@M.endpoint(M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def cancel_order(order_id):
    payload = validation.body()
    validation.req_str(payload, "reason_code")
    order = common.get_order(order_id)
    M.require_order_scope(order)

    if order["fulfillment_status"] not in K.OPEN_ORDER_FULFILLMENT:
        fail(errors.ERR_INVALID_ORDER_STATE)
    if order["settlement_status"] != "SETTLEABLE":
        fail(errors.ERR_INVALID_ORDER_STATE)
    if order["refunded_total_cents"] != 0:
        fail(errors.ERR_ORDER_HAS_ACCEPTED_ADJUSTMENTS)

    store = db.stores.get(order["store_id"])
    released_slot = _slot_held(order)
    was_tablet = order["injection_status"] == "TABLET_FALLBACK"

    order["fulfillment_status"] = "CANCELLED"
    db.touch(order)

    store["open_order_count"] = max(0, store["open_order_count"] - 1)
    if released_slot:
        store["reserved_prep_slots"] = max(0, store["reserved_prep_slots"] - 1)
    if was_tablet:
        store["tablet_backlog_count"] = max(0, store["tablet_backlog_count"] - 1)
    db.touch(store)

    domain.withdraw_open_assignments(order)
    return response.object_response(serializers.order(order))


# -------------------------------------------------------------- dispatch ----
@bp.post("/orders/<order_id>/dispatch")
@M.endpoint(M.STORE_OPERATOR)
def dispatch_order(order_id):
    order = common.get_order(order_id)
    M.require_store_scope(order["store_id"])

    if order["fulfillment_status"] not in K.OPEN_ORDER_FULFILLMENT:
        fail(errors.ERR_INVALID_ORDER_STATE)
    if order["injection_status"] not in ("ACCEPTED", "TABLET_FALLBACK"):
        fail(errors.ERR_ORDER_NOT_INJECTED)
    if order["fulfillment_mode"] != "DELIVERY":
        fail(errors.ERR_ORDER_NOT_DELIVERY)
    if domain.order_assignments(order["id"], ("OFFERED", "ACCEPTED")):
        fail(errors.ERR_ASSIGNMENT_ALREADY_OPEN)

    channel = db.channels.get(order["channel_id"])
    network = domain.select_courier_network(order, channel)
    if network is None:
        fail(errors.ERR_NO_ELIGIBLE_COURIER_NETWORK)

    offered_at = clock.now()
    assignment = db.record()
    assignment.update({
        "order_id": order["id"],
        "courier_network_id": network["id"],
        "state": "OFFERED",
        "offered_at": offered_at,
        "accepted_at": None,
        "handoff_deadline_at": None,
        "occupancy_until": clock.plus_seconds(
            offered_at,
            network["handoff_sla_seconds"] + network["dispatch_buffer_seconds"]),
        "handoff_at": None,
        "delivered_at": None,
        "handoff_lateness_seconds": None,
        "handoff_penalty_cents": 0,
        "sla_breached": False,
        "delivery_fee_cents": 0,
    })
    db.assignments[assignment["id"]] = assignment
    domain.recompute_network_open_assignments(network)
    return response.object_response(serializers.assignment(assignment), 201)
