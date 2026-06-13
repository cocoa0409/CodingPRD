"""Notification read/list routes (PRD §3.7)."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import object_response, array_response
from services.lookup import get_or_404
from validators import paginate

bp = Blueprint("notifications", __name__)


@bp.get("/notifications/<nid>")
def read_notification(nid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.notifications, nid)
    return object_response(db.serialize(rec), 200)


@bp.get("/notifications")
def list_notifications():
    require_roles({"Manager", "Host", "Customer"})
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    channel = request.args.get("channel")
    records = []
    for n in db.notifications.values():
        if subject_type is not None and n["subject_type"] != subject_type:
            continue
        if subject_id is not None and n["subject_id"] != subject_id:
            continue
        if channel is not None and n["channel"] != channel:
            continue
        records.append(n)
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)
