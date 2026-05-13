"""Audit log read endpoint."""
from flask import Blueprint, request

import db
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_log", __name__)


@bp.get("/audit-log")
@require_auth(roles={"ExamAdmin"})
def list_audit_log():
    limit, offset = get_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    rows = []
    for r in db.audit_logs.values():
        if subject_type and r.get("subject_type") != subject_type:
            continue
        if subject_id and r.get("subject_id") != subject_id:
            continue
        rows.append(r)
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = [db.public(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)
