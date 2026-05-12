"""Audit log query route."""
from flask import Blueprint, request

from db import audit_logs, public
from errors import err
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_auth(roles={"ComplianceReviewer", "PlatformAdmin"})
def list_audit():
    items = list(audit_logs.values())
    action_q = request.args.get("action")
    subj_e = request.args.get("subject_entity")
    subj_id = request.args.get("subject_id")
    if action_q:
        items = [x for x in items if x["action"] == action_q]
    if subj_e:
        items = [x for x in items if x["subject_entity"] == subj_e]
    if subj_id:
        items = [x for x in items if x["subject_id"] == subj_id]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([public(x) for x in page], limit, offset, total, 200)
