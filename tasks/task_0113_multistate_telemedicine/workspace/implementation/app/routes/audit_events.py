"""Audit-event listing."""
from flask import Blueprint, jsonify, request

from app.auth import require_roles
from app.responses import success_array
from app.store import store
from app.utils import paginate_sorted, parse_pagination


bp = Blueprint("audit_events", __name__)


@bp.get("/telemed/audit-events")
@require_roles(["PlatformAdmin", "ComplianceOfficer"])
def list_audit_events():
    limit, offset = parse_pagination()
    event_type = request.args.get("event_type")
    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")

    rows = []
    for ev in store.audit_events:
        if event_type and ev.get("event_type") != event_type:
            continue
        if subject_entity and ev.get("subject_entity") != subject_entity:
            continue
        if subject_id and ev.get("subject_id") != subject_id:
            continue
        rows.append(ev)
    sliced, total = paginate_sorted(rows, limit, offset)
    return jsonify(success_array(sliced, limit, offset, total)), 200
