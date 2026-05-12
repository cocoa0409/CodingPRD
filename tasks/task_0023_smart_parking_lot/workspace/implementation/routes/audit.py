"""Audit log endpoints."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, get_pagination
from response import success_list
from services.projection import audit_log_view


bp = Blueprint("audit", __name__)


VALID_ACTIONS = {
    "BILLING_ADJUSTMENT", "RESERVATION_CHANGE", "FINE_WAIVE", "CARD_TRANSFER",
}


@bp.route("/audit-logs", methods=["GET"])
@require_auth(roles={"Auditor", "Operator"})
def list_audit_logs():
    limit, offset = get_pagination()
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    action = request.args.get("action")
    if action is not None and action not in VALID_ACTIONS:
        raise err("ERR_BAD_REQUEST", "action filter is invalid")
    rows = []
    for a in db.audit_logs.values():
        if subject_kind and a.get("subject_kind") != subject_kind:
            continue
        if subject_id and a.get("subject_id") != subject_id:
            continue
        if action and a.get("action") != action:
            continue
        rows.append(a)
    rows.sort(key=lambda a: a.get("_seq", 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([audit_log_view(a) for a in page], limit, offset, total)
