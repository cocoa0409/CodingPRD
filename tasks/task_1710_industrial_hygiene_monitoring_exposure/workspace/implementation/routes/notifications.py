"""Employee notifications (PRD section 3.9)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ACK_FORBIDDEN,
    ERR_NOTIFICATION_INVALID_STATE,
    raise_error,
)
from helpers import get_or_404, list_response, now_ts, touch
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import notification_out

bp = Blueprint("notifications", __name__)


@bp.route("/ih/notifications", methods=["GET"])
def list_notifications():
    require_auth(ALL_ROLES)
    return list_response(list(db.notifications.values()), notification_out, {
        "employee_id": request.args.get("employee_id"),
        "exposure_assessment_id": request.args.get("exposure_assessment_id"),
    })


@bp.route("/ih/notifications/<nid>", methods=["GET"])
def get_notification(nid):
    require_auth(ALL_ROLES)
    return success_object(notification_out(get_or_404(db.notifications, nid, "EmployeeNotification")))


@bp.route("/ih/notifications/<nid>/send", methods=["POST"])
def send_notification(nid):
    user_id, _ = require_auth(("IndustrialHygienist", "SiteSafetyManager"))
    notif = get_or_404(db.notifications, nid, "EmployeeNotification")
    if notif["status"] not in ("PENDING", "OVERDUE"):
        raise_error(ERR_NOTIFICATION_INVALID_STATE, "send requires PENDING or OVERDUE")
    notif["status"] = "SENT"
    notif["sent_at"] = now_ts()
    notif["sent_by_user_id"] = user_id
    touch(notif)
    return success_object(notification_out(notif), 200)


@bp.route("/ih/notifications/<nid>/acknowledge", methods=["POST"])
def acknowledge_notification(nid):
    user_id, _ = require_auth(("Employee",))
    notif = get_or_404(db.notifications, nid, "EmployeeNotification")
    if notif["status"] != "SENT":
        raise_error(ERR_NOTIFICATION_INVALID_STATE, "acknowledge requires SENT")
    if user_id != notif["employee_id"]:
        raise_error(ERR_ACK_FORBIDDEN,
                    "Only the addressed employee may acknowledge the notification")
    notif["status"] = "ACKNOWLEDGED"
    notif["acknowledged_at"] = now_ts()
    touch(notif)
    return success_object(notification_out(notif), 200)
