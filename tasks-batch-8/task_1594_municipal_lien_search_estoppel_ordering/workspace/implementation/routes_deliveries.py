"""Delivery routes: create, get, deliver (freeze snapshot), acknowledge."""
from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_ORDER_OWNER,
    ERR_CLOSING_DATE_PASSED,
    ERR_ORDER_NOT_DELIVERABLE,
    ERR_DELIVERY_ALREADY_PENDING,
)
from helpers import body, _MISSING
from middleware import require_roles, require_any_role
from response import success

bp = Blueprint("deliveries", __name__)


def get_delivery_or_404(did):
    d = db.deliveries.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Delivery not found")
    return d


@bp.post("/deliveries")
def create_delivery():
    require_roles("QAReviewer")
    b = body()
    search_order_id = b.get("search_order_id", _MISSING)
    if search_order_id is _MISSING or not isinstance(search_order_id, str) or not search_order_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "search_order_id is required")
    order = db.search_orders.get(search_order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Search order not found")
    if order["status"] != "READY_FOR_DELIVERY":
        raise ApiError(
            ERR_ORDER_NOT_DELIVERABLE, 409,
            "Order is not READY_FOR_DELIVERY",
        )
    for d in db.deliveries.values():
        if d["search_order_id"] == search_order_id and d["status"] == "READY":
            raise ApiError(ERR_DELIVERY_ALREADY_PENDING, 409, "A READY delivery already exists for the order")
    d = {
        "id": db.new_id(), "search_order_id": search_order_id, "status": "READY",
        "snapshot_payoff_cents": None, "snapshot_fees_cents": None,
        "coverage_fee_cents": None, "liability_cap_cents": None,
        "delivered_at": None, "delivered_to_agent_id": None,
    }
    db.stamp(d)
    db.deliveries[d["id"]] = d
    return success(services.ser_delivery(d), 201)


@bp.get("/deliveries/<did>")
def get_delivery(did):
    require_any_role()
    return success(services.ser_delivery(get_delivery_or_404(did)))


@bp.post("/deliveries/<did>/deliver")
def deliver(did):
    require_roles("QAReviewer")
    d = get_delivery_or_404(did)
    if d["status"] != "READY":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Delivery in {d['status']} cannot be delivered",
        )
    order = db.search_orders.get(d["search_order_id"])
    if order is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Search order not found")
    if order["status"] != "READY_FOR_DELIVERY":
        raise ApiError(ERR_ORDER_NOT_DELIVERABLE, 409, "Order is not READY_FOR_DELIVERY")
    if order["closing_date"] < db.today():
        raise ApiError(ERR_CLOSING_DATE_PASSED, 422, "closing_date is before the current clock date")
    payoff, fees, _claims, _liab = services.order_totals(order)
    coverage_fee, cap = services.liability_cap_projection(fees, order["extended_coverage"])
    d["snapshot_payoff_cents"] = payoff
    d["snapshot_fees_cents"] = fees
    d["coverage_fee_cents"] = coverage_fee
    d["liability_cap_cents"] = cap
    d["delivered_at"] = db.now()
    d["delivered_to_agent_id"] = order["title_agent_id"]
    d["status"] = "DELIVERED"
    touch(d)
    order["status"] = "DELIVERED"
    touch(order)
    return success(services.ser_delivery(d))


@bp.post("/deliveries/<did>/acknowledge")
def acknowledge(did):
    uid = require_roles("TitleAgent")
    d = get_delivery_or_404(did)
    if d["status"] != "DELIVERED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Delivery in {d['status']} cannot be acknowledged",
        )
    order = db.search_orders.get(d["search_order_id"])
    if order is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Search order not found")
    if uid != order["title_agent_id"]:
        raise ApiError(ERR_NOT_ORDER_OWNER, 403, "Only the owning TitleAgent may acknowledge this delivery")
    d["status"] = "ACKNOWLEDGED"
    touch(d)
    return success(services.ser_delivery(d))
