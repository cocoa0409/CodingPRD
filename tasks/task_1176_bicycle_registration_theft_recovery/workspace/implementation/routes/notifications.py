"""Notifications (PRD §3.9)."""
from flask import Blueprint, g, request

import db
from errors import fail
from middleware import require_roles
from models import notification_view
from response import list_response, ok_object
from routes.common import load

bp = Blueprint("notifications", __name__)


@bp.get("/registry/notifications")
@require_roles("Owner", "Registrar", "Admin")
def list_notifications():
    recs = list(db.notifications.values())
    if g.role == "Owner":
        recs = [n for n in recs if n["owner_id"] == g.user_id]
    else:
        owner_filter = request.args.get("owner_id")
        if owner_filter is not None:
            recs = [n for n in recs if n["owner_id"] == owner_filter]
    unread_only = request.args.get("unread_only")
    if unread_only is not None and unread_only.lower() in ("true", "1", "yes"):
        recs = [n for n in recs if not n["read"]]
    return list_response(recs, notification_view)


@bp.get("/registry/notifications/<notification_id>")
@require_roles("Owner", "Registrar", "Admin")
def read_notification(notification_id):
    rec = load(db.notifications, notification_id, "ERR_NOTIFICATION_NOT_FOUND")
    if g.role == "Owner" and rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own notifications")
    return ok_object(notification_view(rec))


@bp.post("/registry/notifications/<notification_id>/mark-read")
@require_roles("Owner")
def mark_read(notification_id):
    rec = load(db.notifications, notification_id, "ERR_NOTIFICATION_NOT_FOUND")
    if rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may mark only their own notifications")
    rec["read"] = True
    db.bump(rec)
    return ok_object(notification_view(rec))
