"""Notification endpoints (nested under tow orders)."""
from flask import Blueprint, request

import db
from clock import iso, now
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services.serialize import public
from validators import paginate_and_respond, require_enum, sort_by_created

bp = Blueprint("notifications", __name__)

RECIPIENT_TYPES = {"OWNER", "LIENHOLDER"}
METHODS = {"CERTIFIED_MAIL", "PUBLICATION", "EMAIL"}


def get_order_or_404(order_id):
    o = db.tow_orders.get(order_id)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    return o


def get_notif_or_404(order_id, nid):
    n = db.notifications.get(nid)
    if n is None or n["tow_order_id"] != order_id:
        raise ApiError("ERR_NOT_FOUND", "Notification not found")
    return n


@bp.route("/tow-orders/<order_id>/notifications", methods=["POST"])
def create_notification(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    order = get_order_or_404(order_id)
    body = get_json_body()
    recipient_type = require_enum(body, "recipient_type", RECIPIENT_TYPES)
    method = require_enum(body, "method", METHODS)
    notif = {
        "tow_order_id": order_id,
        "recipient_type": recipient_type,
        "method": method,
        "sent_at": None,
        "resolved_at": None,
        "republished_from_id": None,
        "status": "DRAFT",
        "_resolved_dt": None,
    }
    db.stamp_create(notif)
    db.notifications[notif["id"]] = notif
    return object_response(public(notif), 201)


@bp.route("/tow-orders/<order_id>/notifications", methods=["GET"])
def list_notifications(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    get_order_or_404(order_id)
    items = [n for n in db.notifications.values() if n["tow_order_id"] == order_id]
    recipient_type = request.args.get("recipient_type")
    status = request.args.get("status")
    if recipient_type is not None:
        items = [n for n in items if n["recipient_type"] == recipient_type]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    items = sort_by_created(items)
    return paginate_and_respond([public(n) for n in items])


@bp.route("/tow-orders/<order_id>/notifications/<nid>", methods=["GET"])
def get_notification(order_id, nid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    get_order_or_404(order_id)
    n = get_notif_or_404(order_id, nid)
    return object_response(public(n), 200)


@bp.route("/tow-orders/<order_id>/notifications/<nid>/send", methods=["POST"])
def send_notification(order_id, nid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    order = get_order_or_404(order_id)
    n = get_notif_or_404(order_id, nid)
    if n["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Notification is not DRAFT")
    if n["recipient_type"] == "LIENHOLDER" and not order.get("lienholder_id"):
        raise ApiError("ERR_NO_LIENHOLDER", "Order has no lienholder on record")
    n["status"] = "SENT"
    n["sent_at"] = iso(now())
    db.touch(n)
    return object_response(public(n), 200)


@bp.route("/tow-orders/<order_id>/notifications/<nid>/confirm-delivery", methods=["POST"])
def confirm_delivery(order_id, nid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    get_order_or_404(order_id)
    n = get_notif_or_404(order_id, nid)
    if n["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Notification is not SENT")
    resolved_dt = now()
    n["status"] = "DELIVERY_CONFIRMED"
    n["resolved_at"] = iso(resolved_dt)
    n["_resolved_dt"] = resolved_dt
    db.touch(n)
    return object_response(public(n), 200)


@bp.route("/tow-orders/<order_id>/notifications/<nid>/mark-returned", methods=["POST"])
def mark_returned(order_id, nid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    get_order_or_404(order_id)
    n = get_notif_or_404(order_id, nid)
    if n["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Notification is not SENT")
    if n["method"] != "CERTIFIED_MAIL":
        raise ApiError("ERR_METHOD_NOT_CERTIFIED", "mark-returned requires CERTIFIED_MAIL")
    resolved_dt = now()
    n["status"] = "CERTIFIED_RETURNED"
    n["resolved_at"] = iso(resolved_dt)
    n["_resolved_dt"] = resolved_dt
    db.touch(n)
    return object_response(public(n), 200)


@bp.route("/tow-orders/<order_id>/notifications/<nid>/mark-undeliverable", methods=["POST"])
def mark_undeliverable(order_id, nid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    get_order_or_404(order_id)
    n = get_notif_or_404(order_id, nid)
    if n["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Notification is not SENT")
    resolved_dt = now()
    n["status"] = "UNDELIVERABLE"
    n["resolved_at"] = iso(resolved_dt)
    # Does NOT start the grace clock: leave _resolved_dt None so eligibility ignores it.
    n["_resolved_dt"] = None
    db.touch(n)
    return object_response(public(n), 200)
