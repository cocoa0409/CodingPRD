"""AuditLog list endpoint."""

from flask import Blueprint, request

from common import paginate_list, parse_pagination, sort_by_created_at
from db import db
from middleware import require_roles
from response import paginated
from services.audit_log import serialize_log


bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_roles("AuditOfficer", "FinanceOfficer")
def get_audit_logs():
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    items = list(db.audit_logs)
    if subject_type:
        items = [e for e in items if e["subject_type"] == subject_type]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    items = sort_by_created_at(items)
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_log(e) for e in page], limit, offset, total)
