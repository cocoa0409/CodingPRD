"""Audit log endpoints."""

from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import array_response
from serializers import audit_log_entry as ser_audit
from validators import get_pagination, paginate


bp = Blueprint("audit_log", __name__)


@bp.get("/audit-log")
@require_roles("COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def list_entries():
    limit, offset = get_pagination(request.args)
    rows = db.audit.all()
    subject_type = request.args.get("subject_type")
    if subject_type:
        rows = [r for r in rows if r["subject_type"] == subject_type]
    subject_id = request.args.get("subject_id")
    if subject_id:
        rows = [r for r in rows if r["subject_id"] == subject_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return array_response(
        [ser_audit(r) for r in page], limit=limit, offset=offset, total_count=total
    )
