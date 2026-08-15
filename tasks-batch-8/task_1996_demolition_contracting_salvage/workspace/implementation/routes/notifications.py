"""NeighborNotification endpoints: creation, delivery with the ordered
blackout -> quiet-hours -> daily-cap checks, and voiding."""

from flask import Blueprint, request

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_BLACKOUT_DATE,
                    ERR_QUIET_HOURS, ERR_DAILY_DELIVERY_CAP)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_notification
from services import (get_project, get_notification, project_notifications,
                      quiet_window_intersects, DAILY_DELIVERY_CAP)
from util import req_str, req_enum, req_date_str

bp = Blueprint("notifications", __name__)

NOTICE_METHODS = ("CERTIFIED_MAIL", "DOOR_HANGER", "POSTING")
NOTIF_READ_ROLES = ("ContractorAdmin", "SiteSupervisor")


@bp.post("/demolition/projects/<pid>/neighbor-notifications")
@require_roles("SiteSupervisor")
def create_notification(pid):
    b = body()
    address = req_str(b, "address")
    method = req_enum(b, "notice_method", NOTICE_METHODS)
    delivery_date = req_date_str(b, "scheduled_delivery_date")
    project = get_project(pid)

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "address": address,
        "notice_method": method,
        "scheduled_delivery_date": delivery_date,
        "status": "PENDING_DELIVERY",
        "delivered_at": None,
    })
    store.notifications[rec["id"]] = rec
    return success(ser_notification(rec), status=201)


@bp.get("/demolition/projects/<pid>/neighbor-notifications")
@require_roles(*NOTIF_READ_ROLES)
def list_notifications(pid):
    project = get_project(pid)
    items = project_notifications(project["id"])
    status_arg = request.args.get("status")
    if status_arg is not None:
        items = [n for n in items if n["status"] == status_arg]
    return list_response(items, ser_notification)


@bp.post("/demolition/neighbor-notifications/<nid>/transition")
@require_roles("SiteSupervisor")
def notification_transition(nid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in ("DELIVER", "VOID"):
        raise err(ERR_VALIDATION, "invalid action")
    notif = get_notification(nid)
    if notif["status"] != "PENDING_DELIVERY":
        raise err(ERR_INVALID_STATE, "transition requires PENDING_DELIVERY")

    if action == "VOID":
        notif["status"] = "VOIDED"
    else:  # DELIVER
        project = store.projects[notif["project_id"]]
        current = now()
        # Timing checks in fixed order: blackout date, then quiet hours, then daily cap.
        today = current.date().isoformat()
        if today in project["blackout_dates"]:
            raise err(ERR_BLACKOUT_DATE, "delivery date is blacked out")
        if quiet_window_intersects(current):
            raise err(ERR_QUIET_HOURS, "delivery occupation intersects the quiet window")
        delivered_today = sum(
            1 for n in project_notifications(project["id"])
            if n["status"] == "DELIVERED" and n["delivered_at"].date() == current.date()
        )
        if delivered_today >= DAILY_DELIVERY_CAP:
            raise err(ERR_DAILY_DELIVERY_CAP, "daily delivery cap reached for this date")
        notif["delivered_at"] = current
        notif["status"] = "DELIVERED"

    touch(notif)
    return success(ser_notification(notif))
