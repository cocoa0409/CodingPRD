"""Audit log endpoint."""
from flask import Blueprint, request

import db
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_logs", __name__)


def _serialize(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


@bp.route("/shuttle/audit-logs", methods=["GET"])
@require_auth(roles={"Auditor", "Dispatcher"})
def list_audit():
    limit, offset = get_pagination()
    et = request.args.get("event_type")
    st = request.args.get("subject_type")
    sid = request.args.get("subject_id")
    items = list(db.audit_logs.values())
    if et:
        items = [a for a in items if a.get("event_type") == et]
    if st:
        items = [a for a in items if a.get("subject_type") == st]
    if sid:
        items = [a for a in items if a.get("subject_id") == sid]
    items.sort(key=lambda a: a.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize(a) for a in page], limit, offset, len(items))
