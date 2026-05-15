"""Audit log query endpoint."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import require_auth
from app.responses import success_array
from app.services.serializers import audit_log_dto
from app.store import store
from app.validation import parse_pagination, paginate


bp = Blueprint("audit", __name__, url_prefix="/fx-risk")


@bp.route("/audit-log", methods=["GET"])
@require_auth(["ComplianceOfficer", "RiskOfficer"])
def list_audit_log():
    with store.lock:
        limit, offset = parse_pagination()
        rows = list(store.audit_log.values())
        event_type = request.args.get("event_type")
        subject_entity = request.args.get("subject_entity")
        subject_id = request.args.get("subject_id")
        if event_type:
            rows = [r for r in rows if r["event_type"] == event_type]
        if subject_entity:
            rows = [r for r in rows if r["subject_entity"] == subject_entity]
        if subject_id:
            rows = [r for r in rows if r["subject_id"] == subject_id]
        page, total = paginate(rows, limit, offset)
        return success_array(
            [audit_log_dto(r) for r in page],
            limit=limit, offset=offset, total_count=total,
        )
