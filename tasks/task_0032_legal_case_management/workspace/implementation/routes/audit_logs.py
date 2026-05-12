"""Audit log read endpoint (PartnerLawyer only)."""

import db
import helpers
import response
import serializers
from flask import Blueprint, request
from middleware import auth_required


bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
@auth_required("PartnerLawyer")
def list_audit_logs():
    limit, offset = helpers.parse_pagination()
    items = list(db.audit_logs)

    if request.args.get("subject_type"):
        items = [a for a in items if a["subject_type"] == request.args["subject_type"]]
    if request.args.get("subject_id"):
        items = [a for a in items if a["subject_id"] == request.args["subject_id"]]
    if request.args.get("actor_id"):
        items = [a for a in items if a["actor_id"] == request.args["actor_id"]]

    items.sort(key=lambda a: a["occurred_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok(
        [serializers.audit_log_dict(a) for a in page],
        limit=limit, offset=offset, total_count=total,
    )
