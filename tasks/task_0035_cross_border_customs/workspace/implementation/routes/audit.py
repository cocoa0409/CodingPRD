"""Audit event listing endpoint."""

from flask import Blueprint, request

from db import DB
from middleware import require_roles
from response import success_array
from services.common import paginate, parse_pagination, sort_by_created_at
from services.serializers import serialize_audit


bp = Blueprint("audit", __name__)


@bp.route("/audit_events", methods=["GET"])
@require_roles("Auditor", "CustomsOfficer")
def list_audit_events():
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    event_type = request.args.get("event_type")

    items = list(DB.audit_events)
    if subject_type:
        items = [e for e in items if e["subject_type"] == subject_type]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]

    items = sort_by_created_at(items)
    sliced, total, has_more = paginate(items, limit, offset)
    return success_array([serialize_audit(e) for e in sliced],
                         limit=limit, offset=offset, total_count=total, has_more=has_more)
