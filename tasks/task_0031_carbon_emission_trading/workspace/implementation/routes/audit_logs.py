"""Audit log read endpoint."""

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
from middleware import auth_required
from serializers import audit_log_entry_dict


bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
@auth_required("Regulator")
def list_audit_logs():
    limit, offset = helpers.parse_pagination()
    items = list(db.audit_log_entries)
    eid = request.args.get("enterprise_id")
    st = request.args.get("subject_type")
    action = request.args.get("action")
    oa = request.args.get("occurred_after")
    ob = request.args.get("occurred_before")
    if eid is not None:
        items = [a for a in items if a.get("enterprise_id") == eid]
    if st is not None:
        items = [a for a in items if a["subject_type"] == st]
    if action is not None:
        items = [a for a in items if a["action"] == action]
    if oa is not None:
        oa_dt = clock.parse_iso(oa)
        items = [a for a in items if a["occurred_at"] >= oa_dt]
    if ob is not None:
        ob_dt = clock.parse_iso(ob)
        items = [a for a in items if a["occurred_at"] <= ob_dt]
    items.sort(key=lambda a: a["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([audit_log_entry_dict(a) for a in page],
                            limit=limit, offset=offset, total_count=total)
