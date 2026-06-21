"""ParentNotification read endpoints (PRD §3.10). Append-only; never created via API."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import err, ERR_FORBIDDEN
from services.common import parse_pagination, sorted_by_creation, paginate
from services.domain import notification_public
from services.lookup import get_notification

bp = Blueprint("notifications", __name__)


@bp.get("/parent-notifications/<notification_id>")
def get_notification_ep(notification_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    rec = get_notification(notification_id)
    if p.role == "Parent" and rec["parent_id"] != p.user_id:
        raise err(ERR_FORBIDDEN, "Parent may only read their own notifications")
    return ok(notification_public(rec), 200)


@bp.get("/parent-notifications")
def list_notifications():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    limit, offset = parse_pagination(request.args)

    records = list(DB.parent_notifications.values())
    for field in ("district_id", "parent_id", "student_id", "bus_trip_id", "kind"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]

    if p.role == "Parent":
        records = [r for r in records if r["parent_id"] == p.user_id]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([notification_public(r) for r in page], limit, offset, total)
