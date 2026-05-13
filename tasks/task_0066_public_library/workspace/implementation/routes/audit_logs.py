"""Audit log read endpoint."""
from flask import Blueprint, request

import db
from response import success_list
from middleware import require_auth, get_pagination
from services.serialize import serialize_audit_log


bp = Blueprint("audit_logs", __name__)


@bp.route("/library/audit-logs", methods=["GET"])
@require_auth(roles={"Admin"})
def list_audit_logs():
    limit, offset = get_pagination()
    event_type = request.args.get("event_type")
    subject_id = request.args.get("subject_id")
    items = list(db.audit_logs.values())
    if event_type:
        items = [a for a in items if a["event_type"] == event_type]
    if subject_id:
        items = [a for a in items if a["subject_id"] == subject_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    sliced = items[offset:offset + limit]
    return success_list([serialize_audit_log(a) for a in sliced], limit, offset, total)
