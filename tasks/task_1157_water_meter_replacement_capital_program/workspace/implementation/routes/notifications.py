"""Customer notification endpoints (PRD 3.4)."""
import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, ser_notification
from flask import Blueprint, request
from validate import body, opt_dt, req_enum, req_str

bp = Blueprint("notifications", __name__)

CHANNELS = ("USPS_MAIL", "CERTIFIED_MAIL", "DOOR_HANGER", "PHONE", "EMAIL")
OUTCOMES = ("DELIVERED", "FAILED", "RETURNED")


@bp.post("/api/notifications")
@require_roles("Scheduler")
def create_notification():
    b = body()
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = req_str(b, "work_order_id")
    wo = get_or_404(db.work_orders, work_order_id, "WorkOrder")
    channel = req_enum(b, "channel", CHANNELS)
    n = base_resource()
    n.update({
        "work_order_id": wo["id"],
        "no_access_case_id": None,
        "channel": channel,
        "sent_at": clock_now(),
        "delivered_at": None,
        "status": "SENT",
    })
    db.notifications[n["id"]] = n
    return ok_object(ser_notification(n), 201)


@bp.post("/api/notifications/<notificationId>/confirm-delivery")
@require_roles("Scheduler")
def confirm_delivery(notificationId):
    n = get_or_404(db.notifications, notificationId, "CustomerNotification")
    b = body()
    outcome = req_enum(b, "outcome", OUTCOMES)
    delivered_at = opt_dt(b, "delivered_at")
    if n["status"] != "SENT":
        raise_err("ERR_INVALID_STATE", "Notification is not SENT")
    if outcome == "DELIVERED":
        n["status"] = "DELIVERED"
        n["delivered_at"] = delivered_at if delivered_at is not None else clock_now()
    else:
        n["status"] = outcome
    touch(n)
    # First DELIVERED notification (any channel) moves CREATED -> NOTIFIED.
    wo = db.work_orders.get(n["work_order_id"])
    if outcome == "DELIVERED" and wo is not None and wo["lifecycle_status"] == "CREATED":
        wo["lifecycle_status"] = "NOTIFIED"
        touch(wo)
    return ok_object(ser_notification(n))


@bp.get("/api/notifications")
@require_roles(*ALL_ROLES)
def list_notifications():
    filters = {}
    for k in ("work_order_id", "no_access_case_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.notifications.values(), filters, ser_notification)


@bp.get("/api/notifications/<notificationId>")
@require_roles(*ALL_ROLES)
def get_notification(notificationId):
    return ok_object(ser_notification(
        get_or_404(db.notifications, notificationId, "CustomerNotification")))
