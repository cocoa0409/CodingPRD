"""Shipment endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import models
import response as resp
import services
import util

bp = Blueprint("shipments", __name__)


@bp.route("/shipments/<sid>/dispatch", methods=["POST"])
def dispatch_shipment(sid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    s = models.get_shipment(sid)
    if s["status"] in ("DELIVERED", "CANCELLED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "shipment is terminal")
    if s["status"] != "PREPARING":
        errors.raise_error(errors.ERR_INVALID_STATE, "shipment must be PREPARING")
    o = db.orders.get(s["order_id"])
    if not o:
        errors.raise_error(errors.ERR_ORDER_NOT_FOUND, "parent order not found")
    if o["status"] != "READY_TO_SHIP":
        errors.raise_error(errors.ERR_INVALID_STATE, "order must be READY_TO_SHIP")

    # Deposit must be fully paid
    if not o.get("deposit_paid_at"):
        errors.raise_error(errors.ERR_DEPOSIT_NOT_PAID, "deposit not fully paid")

    # Cross-entity: parent WorkOrder both dimensions COMPLETED (defensive; already implied by READY_TO_SHIP)
    wos = models.order_work_orders(o["id"])
    if not wos:
        errors.raise_error(errors.ERR_INVALID_STATE, "no work order")
    wo = wos[0]
    if wo["production_status"] != "COMPLETED":
        errors.raise_error(errors.ERR_INVALID_STATE, "production not complete")
    if wo["addressing_status"] not in ("NOT_APPLICABLE", "COMPLETED"):
        errors.raise_error(errors.ERR_INVALID_STATE, "addressing not complete")

    s["status"] = "DISPATCHED"
    s["dispatched_at"] = db.iso_now()
    models.bump(s)
    o["status"] = "SHIPPED"
    models.bump(o)
    return resp.ok(s)


@bp.route("/shipments/<sid>/mark-delivered", methods=["POST"])
def mark_delivered(sid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    s = models.get_shipment(sid)
    if s["status"] in ("DELIVERED", "CANCELLED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "shipment is terminal")
    if s["status"] != "DISPATCHED":
        errors.raise_error(errors.ERR_INVALID_STATE, "shipment must be DISPATCHED")

    o = db.orders.get(s["order_id"])
    if not o:
        errors.raise_error(errors.ERR_ORDER_NOT_FOUND, "parent order not found")
    if o["status"] != "SHIPPED":
        errors.raise_error(errors.ERR_INVALID_STATE, "order must be SHIPPED")

    s["status"] = "DELIVERED"
    s["delivered_at"] = db.iso_now()
    models.bump(s)
    # Release paper reservations BEFORE flipping order status so remove_reservations() logic works cleanly
    services.remove_reservations(o)
    o["status"] = "DELIVERED"
    services.recompute_order_total(o)
    models.bump(o)
    # Archive design
    d = db.designs.get(o["design_id"])
    if d:
        d["status"] = "ARCHIVED"
        models.bump(d)
    return resp.ok(s)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    s = models.get_shipment(sid)
    if role == "Customer":
        o = db.orders.get(s["order_id"])
        if not o or o["customer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not your shipment")
    return resp.ok(s)


@bp.route("/orders/<oid>/shipments", methods=["GET"])
def list_order_shipments(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    limit, offset = util.get_pagination()
    items = [s for s in db.shipments.values() if s["order_id"] == oid]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
