"""Audit entry listing."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_list
from services import serializers
from utils import get_pagination, paginate

bp = Blueprint("audit", __name__)


@bp.route("/audit-entries", methods=["GET"])
@require_roles("Admin", "FinanceManager", "IPManager", "Counsel")
def list_audit():
    limit, offset = get_pagination(request.args)
    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")
    event_type = request.args.get("event_type")
    from_time = request.args.get("from_time")
    to_time = request.args.get("to_time")
    items = list(db.audit_entries)
    if subject_entity:
        items = [a for a in items if a["subject_entity"] == subject_entity]
    if subject_id:
        items = [a for a in items if a["subject_id"] == subject_id]
    if event_type:
        items = [a for a in items if a["event_type"] == event_type]
    if from_time:
        ft = db.parse_iso(from_time)
        if ft:
            items = [a for a in items if db.parse_iso(a["created_at"]) and
                     db.parse_iso(a["created_at"]) >= ft]
    if to_time:
        tt = db.parse_iso(to_time)
        if tt:
            items = [a for a in items if db.parse_iso(a["created_at"]) and
                     db.parse_iso(a["created_at"]) <= tt]
    items.sort(key=lambda a: a["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_audit(a) for a in window]
    return success_list(data, limit, offset, total)
