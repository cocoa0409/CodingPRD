"""Periodic sweeps, recovery analytics and the logical clock endpoint."""

from flask import Blueprint, request

import db
import middleware as mw
import response
from errors import ApiError
from services import aggregates, lookups, orders as order_svc
from util import clock, iso, ratio

bp = Blueprint("ops", __name__)

ANALYTICS_ROLES = (mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS)


@bp.post("/liquidation/pickup-deadline-sweeps")
def pickup_deadline_sweep():
    mw.authenticate((mw.MARKETPLACE_OPS,))
    mw.body()
    changed = []
    sellers = {}
    buyers = {}
    for order in db.ordered(list(db.sale_orders.values())):
        if not order_svc.pickup_overdue(order):
            continue
        order["logistics_status"] = "ABANDONED"
        order["abandoned_at"] = clock.now()
        db.touch(order)
        changed.append(order)

        for appointment in lookups.appointments_of_order(order["id"]):
            if appointment["appointment_status"] == "SCHEDULED":
                appointment["appointment_status"] = "CANCELLED"
                db.touch(appointment)

        lot = lookups.lot_of_order(order)
        if lot["lot_status"] == "SOLD":
            lot["lot_status"] = "RELIST_PENDING"
            db.touch(lot)
        sellers[lot["seller_id"]] = lot["seller_id"]
        buyers[order["buyer_id"]] = order["buyer_id"]

    for seller_id in sellers:
        seller = db.sellers.get(seller_id)
        if seller is not None:
            aggregates.recompute_seller_recovery(seller)
    for buyer_id in buyers:
        buyer = db.buyers.get(buyer_id)
        if buyer is not None:
            aggregates.recompute_buyer_exposure(buyer)
    return response.bare_array(db.views("sale_order", changed))


@bp.post("/liquidation/payment-late-fee-sweeps")
def payment_late_fee_sweep():
    mw.authenticate((mw.MARKETPLACE_OPS,))
    mw.body()
    changed = []
    buyers = {}
    for order in db.ordered(list(db.sale_orders.values())):
        if not order_svc.late_fee_due(order):
            continue
        order_svc.apply_late_fee(order)
        db.touch(order)
        changed.append(order)
        buyers[order["buyer_id"]] = order["buyer_id"]

    for buyer_id in buyers:
        buyer = db.buyers.get(buyer_id)
        if buyer is not None:
            aggregates.recompute_buyer_exposure(buyer)
    return response.bare_array(db.views("sale_order", changed))


def _variants(lots, orders):
    """Both recovery variants over an arbitrary lot/order population."""
    gross_hammer = sum(
        int(order["hammer_price_cents"]) for order in orders
        if order["logistics_status"] != "ABANDONED"
    )
    listed_retail = sum(
        int(lot["declared_retail_value_cents"]) for lot in lots
        if lot["lot_status"] in ("LISTED", "SOLD", "RELIST_PENDING")
    )
    net_proceeds = sum(
        int(order["seller_net_proceeds_cents"] or 0) for order in orders
        if order["settlement_basis"] == "FINAL"
    )
    sold_retail = sum(
        int(lot["declared_retail_value_cents"]) for lot in lots
        if lot["lot_status"] == "SOLD"
    )
    return {
        "gross_hammer_cents": gross_hammer,
        "listed_retail_value_cents": listed_retail,
        "gross_recovery_rate": ratio(gross_hammer, listed_retail, 4),
        "net_proceeds_cents": net_proceeds,
        "sold_retail_value_cents": sold_retail,
        "net_recovery_rate": ratio(net_proceeds, sold_retail, 4),
    }


def _channels_of_lot(lot):
    return {
        listing["resale_channel"] for listing in lookups.listings_of_lot(lot["id"])
    }


@bp.get("/liquidation/recovery-analytics")
def recovery_analytics():
    user_id, role = mw.authenticate(ANALYTICS_ROLES)
    seller_id = request.args.get("seller_id")
    if not seller_id:
        raise ApiError("ERR_INVALID_REQUEST", "seller_id is required.")
    # band 4 — a SellerOps caller may only name its own seller
    if role == mw.SELLER_OPS and seller_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # band 6
    lookups.seller(seller_id)

    group_by = request.args.get("group_by") or "NONE"
    if group_by not in mw.GROUP_BY_VALUES:
        raise ApiError("ERR_INVALID_REQUEST", "group_by is not a recognised value.")
    category_code = request.args.get("category_code")
    if category_code is not None and category_code not in mw.CATEGORY_CODES:
        raise ApiError("ERR_INVALID_REQUEST", "category_code is not a recognised value.")
    resale_channel = request.args.get("resale_channel")
    if resale_channel is not None and resale_channel not in mw.RESALE_CHANNELS:
        raise ApiError("ERR_INVALID_REQUEST", "resale_channel is not a recognised value.")

    lots = db.ordered(lookups.lots_of_seller(seller_id))
    if category_code is not None:
        lots = [lot for lot in lots if lot["category_code"] == category_code]
    if resale_channel is not None:
        lots = [lot for lot in lots if resale_channel in _channels_of_lot(lot)]
    lot_ids = {lot["id"] for lot in lots}

    orders = []
    for order in db.ordered(lookups.orders_of_seller(seller_id)):
        listing = lookups.listing_of_order(order)
        if listing["lot_id"] not in lot_ids:
            continue
        if resale_channel is not None and listing["resale_channel"] != resale_channel:
            continue
        orders.append(order)

    payload = {"seller_id": seller_id, "group_by": group_by}
    payload.update(_variants(lots, orders))

    groups = []
    if group_by == "CATEGORY":
        keys = sorted({lot["category_code"] for lot in lots})
        for key in keys:
            group_lots = [lot for lot in lots if lot["category_code"] == key]
            group_lot_ids = {lot["id"] for lot in group_lots}
            group_orders = [
                order for order in orders
                if lookups.listing_of_order(order)["lot_id"] in group_lot_ids
            ]
            entry = {"key": key}
            entry.update(_variants(group_lots, group_orders))
            groups.append(entry)
    elif group_by == "CHANNEL":
        keys = set()
        for lot in lots:
            keys |= _channels_of_lot(lot)
        for key in sorted(keys):
            group_lots = [lot for lot in lots if key in _channels_of_lot(lot)]
            group_orders = [
                order for order in orders
                if lookups.listing_of_order(order)["resale_channel"] == key
            ]
            entry = {"key": key}
            entry.update(_variants(group_lots, group_orders))
            groups.append(entry)
    payload["groups"] = groups
    return response.success(payload)


@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.authenticate(mw.ALL_ROLES)
    payload = mw.body()
    instant = mw.req_datetime(payload, "current_utc")
    clock.set(instant)
    return response.success({"current_utc": iso(instant)})
