"""Order, OrderLine, and Shipment endpoints."""
from flask import Blueprint, request

import clock
import db as _db
from db import db, new_entity, touch
from errors import (ApiError, invalid_request, invalid_state, not_found,
                    stale_version, unauthorized)
from helpers import (body, get_or_404, opt_int, opt_str, paginate,
                     pagination_params, public, req_date, req_int, req_str)
from middleware import require, require_member_ownership
from response import success
from services import (SHOP_HOME_STATE, clawback_loyalty, credit_loyalty,
                      compute_unit_price, fefo_allocate, fefo_check,
                      order_lines, recompute_on_hand, recompute_order_totals,
                      restore_allocation, sku_prohibited_in_state)

bp = Blueprint("orders", __name__)

ORDER_READ = ["PlatformAdmin", "ShopStaff", "Member"]
ORDER_WRITE = ["Member", "ShopStaff"]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@bp.post("/orders")
def create_order():
    role, uid = require(ORDER_WRITE)
    data = body()
    # FK existence (priority 3)
    member_id = data.get("member_id")
    if member_id is not None and isinstance(member_id, str):
        get_or_404(db["members"], member_id)
    sub_id = data.get("applied_club_subscription_id")
    if sub_id is not None:
        if not isinstance(sub_id, str):
            raise invalid_request("applied_club_subscription_id must be a string")
        get_or_404(db["club_subscriptions"], sub_id)
    # shape (priority 4)
    member_id = req_str(data, "member_id")
    get_or_404(db["members"], member_id)
    if role == "Member" and uid != member_id:
        raise unauthorized("Member may only create own orders")
    channel = req_str(data, "channel")
    if channel not in ("RETAIL", "DTC"):
        raise invalid_request("channel must be RETAIL or DTC")
    ship_to = data.get("ship_to_state_code")
    if channel == "DTC":
        ship_to = req_str(data, "ship_to_state_code")
    elif ship_to is not None and not isinstance(ship_to, str):
        raise invalid_request("ship_to_state_code must be a string")
    redeemed = opt_int(data, "loyalty_points_redeemed", 0, min_v=0)
    # state-level: applied subscription must be ACTIVE and belong to member
    if sub_id is not None:
        sub = db["club_subscriptions"][sub_id]
        if sub["member_id"] != member_id:
            raise invalid_request(
                "applied_club_subscription_id does not belong to member")
        if sub["status"] != "ACTIVE":
            raise invalid_state("Applied club subscription is not ACTIVE")
    ent = new_entity({
        "member_id": member_id,
        "channel": channel,
        "ship_to_state_code": ship_to,
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "shipping_charge_cents": 0,
        "tax_cents": 0,
        "grand_total_cents": 0,
        "loyalty_points_redeemed": redeemed or 0,
        "loyalty_points_earned": 0,
        "applied_club_subscription_id": sub_id,
        "_earned_credited": False,
    })
    db["orders"][ent["id"]] = ent
    recompute_order_totals(ent)
    return success(public(ent), status=201)


@bp.get("/orders")
def list_orders():
    role, uid = require(ORDER_READ)
    limit, offset = pagination_params()
    member_id = request.args.get("member_id")
    channel = request.args.get("channel")
    ful = request.args.get("fulfillment_status")
    items = list(db["orders"].values())
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise unauthorized("Member may only list own orders")
        items = [o for o in items if o["member_id"] == uid]
    elif member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if channel is not None:
        items = [o for o in items if o["channel"] == channel]
    if ful is not None:
        items = [o for o in items if o["fulfillment_status"] == ful]
    page, pg = paginate(items, limit, offset)
    return success([public(o) for o in page], response_type="array",
                   pagination=pg)


@bp.get("/orders/<oid>")
def get_order(oid):
    role, uid = require(ORDER_READ)
    ent = get_or_404(db["orders"], oid)
    require_member_ownership(role, uid, ent["member_id"])
    return success(public(ent))


@bp.get("/orders/<oid>/lines")
def list_lines(oid):
    role, uid = require(ORDER_READ)
    order = get_or_404(db["orders"], oid)
    require_member_ownership(role, uid, order["member_id"])
    limit, offset = pagination_params()
    page, pg = paginate(order_lines(oid), limit, offset)
    return success([public(l) for l in page], response_type="array",
                   pagination=pg)


@bp.post("/orders/<oid>/lines")
def add_line(oid):
    role, uid = require(ORDER_WRITE)
    order = get_or_404(db["orders"], oid)
    data = body()
    sku_id = data.get("sku_id")
    if sku_id is not None and isinstance(sku_id, str):
        get_or_404(db["skus"], sku_id)
    sku_id = req_str(data, "sku_id")
    sku = get_or_404(db["skus"], sku_id)
    if role == "Member" and uid != order["member_id"]:
        raise unauthorized("Member may only modify own orders")
    qty = req_int(data, "qty", min_v=1)
    if order["fulfillment_status"] != "DRAFT":
        raise invalid_state("Order is not DRAFT")
    if sku["discontinued"]:
        raise ApiError("ERR_SKU_DISCONTINUED", 422,
                       "Discontinued SKU cannot be added to orders")
    unit = compute_unit_price(sku, order)
    ent = new_entity({
        "order_id": oid,
        "sku_id": sku_id,
        "qty": qty,
        "unit_price_cents": unit,
        "extended_price_cents": unit * qty,
        "lot_allocation": [],
    })
    db["order_lines"][ent["id"]] = ent
    recompute_order_totals(order)
    touch(order)
    return success(public(ent), status=201)


@bp.delete("/orders/<oid>/lines/<lid>")
def delete_line(oid, lid):
    role, uid = require(ORDER_WRITE)
    order = get_or_404(db["orders"], oid)
    line = db["order_lines"].get(lid)
    if line is None or line["order_id"] != oid:
        raise not_found("Order line not found under this order")
    if role == "Member" and uid != order["member_id"]:
        raise unauthorized("Member may only modify own orders")
    if order["fulfillment_status"] != "DRAFT":
        raise invalid_state("Order is not DRAFT")
    del db["order_lines"][lid]
    recompute_order_totals(order)
    touch(order)
    return success({}, status=204)


@bp.post("/orders/<oid>/submit")
def submit_order(oid):
    role, uid = require(ORDER_WRITE)
    order = get_or_404(db["orders"], oid)
    data = body()
    if role == "Member" and uid != order["member_id"]:
        raise unauthorized("Member may only submit own orders")
    expected = data.get("expected_order_version")
    member = db["members"].get(order["member_id"])
    lines = order_lines(oid)
    # (5) state
    if order["fulfillment_status"] != "DRAFT":
        raise invalid_state("Order is not DRAFT")
    # (6) age attestation + discontinued
    for line in lines:
        sku = db["skus"].get(line["sku_id"])
        if sku is None:
            raise not_found("Referenced SKU does not exist")
        if sku["age_neutral_class"] == "ADULT_ONLY_REQUIRED":
            if member is None or member["age_attestation_status"] != "ATTESTED":
                raise ApiError("ERR_AGE_ATTESTATION_REQUIRED", 422,
                               "Member must be ATTESTED for ADULT_ONLY_REQUIRED SKU")
    for line in lines:
        sku = db["skus"][line["sku_id"]]
        if sku["discontinued"]:
            raise ApiError("ERR_SKU_DISCONTINUED", 422,
                           "Discontinued SKU cannot be ordered")
    # DTC referential checks
    rule = None
    allow_quarantine_override = False
    if order["channel"] == "DTC":
        state_code = order.get("ship_to_state_code")
        if not state_code:
            raise invalid_request("ship_to_state_code required for DTC")
        for r in db["shipping_state_rules"].values():
            if r["state_code"] == state_code:
                rule = r
                break
        if rule is None:
            raise not_found("ShippingStateRule not found for destination state")
        # (13) DTC permission
        if not rule["allows_dtc"]:
            raise ApiError("ERR_DTC_STATE_PROHIBITED", 422,
                           "Destination state does not allow DTC")
        # (14) ABV cap
        for line in lines:
            sku = db["skus"][line["sku_id"]]
            if sku["abv_basis_points"] > rule["abv_cap_basis_points"]:
                raise ApiError("ERR_SKU_ABV_STATE_EXCEEDED", 422,
                               "SKU abv exceeds destination state cap")
        # (15) SKU state prohibition
        for line in lines:
            sku = db["skus"][line["sku_id"]]
            category = db["categories"].get(sku["category_id"])
            if category is not None and sku_prohibited_in_state(
                    sku, category, state_code):
                raise ApiError("ERR_SKU_STATE_PROHIBITED", 422,
                               "SKU prohibited in destination state")
    else:
        # RETAIL: ShopStaff may override to allocate from QUARANTINED lots
        if role in ("ShopStaff", "PlatformAdmin") and data.get("override") is True:
            allow_quarantine_override = True
    # (16) loyalty redemption
    redeemed = order.get("loyalty_points_redeemed") or 0
    if member is None or member["loyalty_points_balance"] < redeemed:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422,
                       "Member loyalty balance does not cover redemption")
    # (17) inventory sufficiency (checked for ALL lines before any mutation)
    for line in lines:
        if not fefo_check(line["sku_id"], line["qty"],
                          allow_quarantined=allow_quarantine_override):
            raise ApiError("ERR_INSUFFICIENT_INVENTORY", 422,
                           "FEFO lot walk cannot satisfy demand")
    # (19) optimistic concurrency
    if expected is not None and expected != order["version"]:
        raise stale_version()
    # commit: allocate lots
    affected = set()
    for line in lines:
        line["lot_allocation"] = fefo_allocate(
            line["sku_id"], line["qty"],
            allow_quarantined=allow_quarantine_override)
        touch(line)
        affected.add(line["sku_id"])
    for sku_id in affected:
        recompute_on_hand(sku_id)
    # loyalty redemption consumed
    if redeemed:
        member["loyalty_points_balance"] -= redeemed
        touch(member)
    recompute_order_totals(order)
    order["payment_status"] = "AUTHORIZED"
    order["fulfillment_status"] = "PICKING"
    touch(order)
    return success(public(order))


@bp.post("/orders/<oid>/pack")
def pack_order(oid):
    require(["ShopStaff"])
    order = get_or_404(db["orders"], oid)
    if order["fulfillment_status"] != "PICKING":
        raise invalid_state("Order is not PICKING")
    order["fulfillment_status"] = "PACKED"
    touch(order)
    return success(public(order))


@bp.post("/orders/<oid>/pickup")
def pickup_order(oid):
    require(["ShopStaff"])
    order = get_or_404(db["orders"], oid)
    if order["fulfillment_status"] != "PACKED":
        raise invalid_state("Order is not PACKED")
    if order["channel"] != "RETAIL":
        raise invalid_state("Pickup is only valid for RETAIL orders")
    order["fulfillment_status"] = "PICKED_UP"
    order["payment_status"] = "CAPTURED"
    touch(order)
    member = db["members"].get(order["member_id"])
    if member is not None and not order.get("_earned_credited"):
        credit_loyalty(member, order["loyalty_points_earned"])
        order["_earned_credited"] = True
    return success(public(order))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    role, uid = require(ORDER_WRITE)
    order = get_or_404(db["orders"], oid)
    if role == "Member" and uid != order["member_id"]:
        raise unauthorized("Member may only cancel own orders")
    status = order["fulfillment_status"]
    if status not in ("DRAFT", "PICKING"):
        raise invalid_state("Order cannot be cancelled in its current state")
    if status == "PICKING" and role == "Member":
        raise unauthorized("Only ShopStaff may cancel a PICKING order")
    if status == "PICKING" and order["payment_status"] not in ("AUTHORIZED", "UNPAID"):
        raise invalid_state("Payment state does not permit cancellation")
    member = db["members"].get(order["member_id"])
    if status == "PICKING":
        affected = set()
        for line in order_lines(oid):
            restore_allocation(line.get("lot_allocation"))
            line["lot_allocation"] = []
            touch(line)
            affected.add(line["sku_id"])
        for sku_id in affected:
            recompute_on_hand(sku_id)
        order["payment_status"] = "VOIDED"
    # loyalty redemption reversed
    redeemed = order.get("loyalty_points_redeemed") or 0
    if redeemed and member is not None:
        member["loyalty_points_balance"] += redeemed
        touch(member)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success(public(order))


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/shipments")
def create_shipment(oid):
    require(["ShopStaff"])
    order = get_or_404(db["orders"], oid)
    data = body()
    sub_id = data.get("club_subscription_id")
    if sub_id is not None:
        if not isinstance(sub_id, str):
            raise invalid_request("club_subscription_id must be a string")
        get_or_404(db["club_subscriptions"], sub_id)
    carrier = req_str(data, "carrier")
    tracking = req_str(data, "tracking_no")
    shipped_on = req_date(data, "shipped_on")
    if order["fulfillment_status"] != "PACKED":
        raise invalid_state("Order is not PACKED")
    if order["channel"] != "DTC":
        raise invalid_state("Shipments are only valid for DTC orders")
    ent = new_entity({
        "order_id": oid,
        "club_subscription_id": sub_id,
        "carrier": carrier,
        "tracking_no": tracking,
        "status": "LABEL_CREATED",
        "shipped_on": shipped_on,
        "delivered_on": None,
    })
    db["shipments"][ent["id"]] = ent
    order["fulfillment_status"] = "SHIPPED"
    touch(order)
    return success(public(ent), status=201)


@bp.get("/orders/<oid>/shipments")
def list_order_shipments(oid):
    role, uid = require(ORDER_READ)
    order = get_or_404(db["orders"], oid)
    require_member_ownership(role, uid, order["member_id"])
    limit, offset = pagination_params()
    items = [s for s in db["shipments"].values() if s["order_id"] == oid]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)


@bp.get("/shipments/<sid>")
def get_shipment(sid):
    role, uid = require(ORDER_READ)
    ent = get_or_404(db["shipments"], sid)
    order = db["orders"].get(ent["order_id"])
    if role == "Member" and (order is None or order["member_id"] != uid):
        raise unauthorized("Member may only view own shipments")
    return success(public(ent))


def _shipment_transition(sid, from_states, to_state):
    require(["ShopStaff", "PlatformAdmin"])
    ship = get_or_404(db["shipments"], sid)
    if ship["status"] not in from_states:
        raise invalid_state("Shipment state does not permit this transition")
    ship["status"] = to_state
    touch(ship)
    return ship


@bp.post("/shipments/<sid>/mark-in-transit")
def mark_in_transit(sid):
    ship = _shipment_transition(sid, {"LABEL_CREATED"}, "IN_TRANSIT")
    return success(public(ship))


@bp.post("/shipments/<sid>/mark-out-for-delivery")
def mark_out_for_delivery(sid):
    ship = _shipment_transition(sid, {"IN_TRANSIT"}, "OUT_FOR_DELIVERY")
    return success(public(ship))


@bp.post("/shipments/<sid>/mark-delivered")
def mark_delivered(sid):
    require(["ShopStaff", "PlatformAdmin"])
    ship = get_or_404(db["shipments"], sid)
    data = body()
    delivered_on = req_date(data, "delivered_on")
    if ship["status"] != "OUT_FOR_DELIVERY":
        raise invalid_state("Shipment is not OUT_FOR_DELIVERY")
    ship["status"] = "DELIVERED"
    ship["delivered_on"] = delivered_on
    touch(ship)
    # bubble up to order
    order = db["orders"].get(ship["order_id"])
    if order is not None:
        order["payment_status"] = "CAPTURED"
        order["fulfillment_status"] = "DELIVERED"
        touch(order)
        member = db["members"].get(order["member_id"])
        if member is not None and not order.get("_earned_credited"):
            credit_loyalty(member, order["loyalty_points_earned"])
            order["_earned_credited"] = True
    sub_id = ship.get("club_subscription_id")
    if sub_id:
        sub = db["club_subscriptions"].get(sub_id)
        if sub is not None:
            sub["shipments_fulfilled"] += 1
            touch(sub)
    return success(public(ship))


@bp.post("/shipments/<sid>/mark-returned")
def mark_returned(sid):
    ship = _shipment_transition(sid, {"IN_TRANSIT"}, "RETURNED")
    order = db["orders"].get(ship["order_id"])
    if order is not None:
        order["payment_status"] = "REFUNDED_FULL"
        affected = set()
        for line in order_lines(order["id"]):
            restore_allocation(line.get("lot_allocation"))
            line["lot_allocation"] = []
            touch(line)
            affected.add(line["sku_id"])
        for sku_id in affected:
            recompute_on_hand(sku_id)
        _refund_clawback(order)
        touch(order)
    return success(public(ship))


@bp.post("/shipments/<sid>/mark-lost")
def mark_lost(sid):
    ship = _shipment_transition(sid, {"OUT_FOR_DELIVERY"}, "LOST")
    order = db["orders"].get(ship["order_id"])
    if order is not None:
        order["payment_status"] = "REFUNDED_FULL"
        _refund_clawback(order)  # no inventory restore — bottles are lost
        touch(order)
    return success(public(ship))


def _refund_clawback(order):
    member = db["members"].get(order["member_id"])
    if member is None:
        return
    if order.get("_earned_credited"):
        clawback_loyalty(member, order["loyalty_points_earned"])
        order["_earned_credited"] = False
    redeemed = order.get("loyalty_points_redeemed") or 0
    if redeemed:
        member["loyalty_points_balance"] += redeemed
        touch(member)
