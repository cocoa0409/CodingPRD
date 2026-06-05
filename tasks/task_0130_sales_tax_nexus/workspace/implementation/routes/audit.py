"""AuditLogEntry read endpoints (§2.7). Visible only to Auditor and PlatformAdmin."""
from flask import Blueprint, request

import db
from middleware import require
from response import object_response, array_response
from services import common, serializers

bp = Blueprint("audit", __name__)


@bp.get("/audit-log-entries/<rec_id>")
@require("Auditor", "PlatformAdmin")
def get_entry(rec_id):
    rec = common.get_or_404(db.audit_log_entries, rec_id, "audit log entry")
    return object_response(serializers.audit_log_entry(rec))


@bp.get("/audit-log-entries")
@require("Auditor", "PlatformAdmin")
def list_entries():
    records = list(db.audit_log_entries.values())
    a = request.args
    if a.get("seller_id") is not None:
        records = [r for r in records if r["seller_id"] == a.get("seller_id")]
    if a.get("subject_entity") is not None:
        records = [r for r in records if r["subject_entity"] == a.get("subject_entity")]
    if a.get("subject_id") is not None:
        records = [r for r in records if r["subject_id"] == a.get("subject_id")]
    items, limit, offset, total = common.paginate(records, serializers.audit_log_entry)
    return array_response(items, limit, offset, total)
