"""RedemptionOrder endpoints."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from db import db
from errors import (
    ERR_DELIVERY_TERMINAL,
    ERR_FORBIDDEN,
    ERR_INSUFFICIENT_POINTS,
    ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_STATE,
    ERR_ITEM_UNAVAILABLE,
    ERR_RESIDENT_INACTIVE,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.common import (
    check_version,
    get_json_body,
    iso_z,
    paginate,
    parse_pagination,
    require_int,
    require_str,
)
from services.ledger import append_transaction
from services.lookup import (
    get_community,
    get_household,
    get_mall_item,
    get_redemption_order,
    get_resident_by_id,
)

bp = Blueprint("redemption_orders", __name__)

TERMINAL_STATES = {"DELIVERED", "REJECTED", "RETURNED"}


@bp.post("/communities/<community_id>/redemption-orders")
@require_roles("Resident")
def submit_order(community_id: str):
    get_community(community_id)
    body = get_json_body()
    mall_item_id = require_str(body, "mall_item_id", min_len=1, max_len=200)
    quantity = require_int(body, "quantity", minimum=1, maximum=50)
    household_id = require_str(body, "household_id", min_len=1, max_len=200)
    resident_id = require_str(body, "resident_id", min_len=1, max_len=200)

    # Ownership: resident_id must equal X-User-ID, and that resident must
    # belong to the household_id supplied in the body.
    if resident_id != g.user_id:
        raise_api_error(ERR_FORBIDDEN, "resident_id must equal X-User-ID.")
    resident = get_resident_by_id(g.user_id)
    if resident is None or resident.get("household_id") != household_id:
        raise_api_error(ERR_FORBIDDEN, "Resident does not belong to this household.")
    household = db.households.get(household_id)
    if household is None or household.get("community_id") != community_id:
        raise_api_error(ERR_FORBIDDEN, "Household does not belong to this community.")

    # Priority 8 — ERR_RESIDENT_INACTIVE
    if not (resident["identity_status"] == "VERIFIED" and resident["account_status"] == "ACTIVE"):
        raise_api_error(ERR_RESIDENT_INACTIVE, "Resident must be VERIFIED+ACTIVE.")

    # Priority 12 — ERR_ITEM_UNAVAILABLE (LISTED and same community)
    item = db.mall_items.get(mall_item_id)
    if (
        item is None
        or item.get("status") != "LISTED"
        or item.get("community_id") != community_id
    ):
        raise_api_error(ERR_ITEM_UNAVAILABLE, "MallItem is not LISTED in this community.")

    unit_cost = int(item["cost_points"])
    total_cost = unit_cost * quantity

    obj = {
        "household_id": household_id,
        "resident_id": resident_id,
        "mall_item_id": mall_item_id,
        "quantity": quantity,
        "unit_cost_points": unit_cost,
        "total_cost_points": total_cost,
        "channel": item["channel"],
        "status": "SUBMITTED",
        "confirmed_at": None,
        "delivered_at": None,
    }
    db.stamp_create(obj)
    db.redemption_orders[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


def _ensure_not_terminal(order: dict):
    if order["status"] in TERMINAL_STATES:
        raise_api_error(ERR_DELIVERY_TERMINAL, f"Order is in terminal state {order['status']}.")


@bp.post("/communities/<community_id>/redemption-orders/<order_id>/confirm")
@require_roles("CommunityAdmin")
def confirm_order(community_id: str, order_id: str):
    order = get_redemption_order(community_id, order_id)
    body = get_json_body()
    check_version(body, order)
    _ensure_not_terminal(order)
    if order["status"] != "SUBMITTED":
        raise_api_error(ERR_INVALID_STATE, "Order must be SUBMITTED to confirm.")

    item = db.mall_items.get(order["mall_item_id"])
    household = db.households.get(order["household_id"])
    if item is None or household is None:
        raise_api_error(ERR_INVALID_STATE, "Related entities not found.")

    # Priority 13 — ERR_INSUFFICIENT_STOCK
    if item["stock"] < order["quantity"]:
        raise_api_error(ERR_INSUFFICIENT_STOCK, "Stock is insufficient.")
    # Priority 14 — ERR_INSUFFICIENT_POINTS
    if household["points_balance"] < order["total_cost_points"]:
        raise_api_error(ERR_INSUFFICIENT_POINTS, "Household has insufficient points.")

    # Apply
    item["stock"] -= order["quantity"]
    db.stamp_update(item)
    household["points_balance"] -= order["total_cost_points"]
    db.stamp_update(household)
    append_transaction(
        household,
        kind="REDEMPTION_DEBIT",
        amount=-int(order["total_cost_points"]),
        related_entity_kind="REDEMPTION_ORDER",
        related_entity_id=order["id"],
    )
    order["status"] = "CONFIRMED"
    order["confirmed_at"] = db.now_iso()
    db.stamp_update(order)
    return jsonify(success_response(order)), 200


@bp.post("/communities/<community_id>/redemption-orders/<order_id>/reject")
@require_roles("CommunityAdmin")
def reject_order(community_id: str, order_id: str):
    order = get_redemption_order(community_id, order_id)
    body = get_json_body()
    check_version(body, order)
    _ensure_not_terminal(order)
    if order["status"] != "SUBMITTED":
        raise_api_error(ERR_INVALID_STATE, "Order must be SUBMITTED to reject.")
    reason = require_str(body, "reason", min_len=1, max_len=500)
    order["status"] = "REJECTED"
    db.stamp_update(order)
    return jsonify(success_response(order)), 200


@bp.post("/communities/<community_id>/redemption-orders/<order_id>/fulfill")
@require_roles("CommunityAdmin")
def fulfill_order(community_id: str, order_id: str):
    order = get_redemption_order(community_id, order_id)
    body = get_json_body()
    check_version(body, order)
    _ensure_not_terminal(order)
    if order["status"] != "CONFIRMED":
        raise_api_error(ERR_INVALID_STATE, "Order must be CONFIRMED to fulfill.")
    order["status"] = "FULFILLED"
    db.stamp_update(order)
    return jsonify(success_response(order)), 200


@bp.post("/communities/<community_id>/redemption-orders/<order_id>/deliver")
@require_roles("CommunityAdmin")
def deliver_order(community_id: str, order_id: str):
    order = get_redemption_order(community_id, order_id)
    body = get_json_body()
    check_version(body, order)
    _ensure_not_terminal(order)
    if order["status"] != "FULFILLED":
        raise_api_error(ERR_INVALID_STATE, "Order must be FULFILLED to deliver.")
    order["status"] = "DELIVERED"
    order["delivered_at"] = db.now_iso()
    db.stamp_update(order)
    return jsonify(success_response(order)), 200


@bp.post("/communities/<community_id>/redemption-orders/<order_id>/return")
@require_roles("CommunityAdmin")
def return_order(community_id: str, order_id: str):
    order = get_redemption_order(community_id, order_id)
    body = get_json_body()
    check_version(body, order)
    _ensure_not_terminal(order)
    if order["status"] != "FULFILLED":
        raise_api_error(ERR_INVALID_STATE, "Order must be FULFILLED to return.")
    reason = require_str(body, "reason", min_len=1, max_len=500)

    item = db.mall_items.get(order["mall_item_id"])
    household = db.households.get(order["household_id"])
    if item is None or household is None:
        raise_api_error(ERR_INVALID_STATE, "Related entities not found.")

    item["stock"] += order["quantity"]
    db.stamp_update(item)
    household["points_balance"] += order["total_cost_points"]
    db.stamp_update(household)
    append_transaction(
        household,
        kind="REDEMPTION_REFUND",
        amount=int(order["total_cost_points"]),
        related_entity_kind="REDEMPTION_ORDER",
        related_entity_id=order["id"],
    )
    order["status"] = "RETURNED"
    db.stamp_update(order)
    return jsonify(success_response(order)), 200


@bp.get("/communities/<community_id>/redemption-orders/<order_id>")
@require_roles("CommunityAdmin", "Resident")
def read_order(community_id: str, order_id: str):
    order = get_redemption_order(community_id, order_id)
    if g.user_role == "Resident":
        me = get_resident_by_id(g.user_id)
        # Resident can read their own household's orders
        if me is None or me.get("household_id") != order["household_id"]:
            raise_api_error(ERR_FORBIDDEN, "Resident does not own this redemption order.")
    return jsonify(success_response(order)), 200


@bp.get("/communities/<community_id>/redemption-orders")
@require_roles("CommunityAdmin")
def list_orders(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    household_id = request.args.get("household_id")

    # Build list of orders in this community
    items = []
    for o in db.redemption_orders.values():
        hh = db.households.get(o["household_id"])
        if hh is None or hh["community_id"] != community_id:
            continue
        if status_filter is not None and o["status"] != status_filter:
            continue
        if household_id is not None and o["household_id"] != household_id:
            continue
        items.append(o)
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
