"""Audit log and external-event read endpoints."""

from flask import Blueprint, request

import db
from middleware import require_role
from response import success_list, parse_pagination
from services.serializers import audit_log_view, external_event_view


bp = Blueprint("audit", __name__)


@bp.route("/audit-logs", methods=["GET"])
def list_audit_logs():
    require_role("ProjectManager")
    limit, offset = parse_pagination(request.args)
    filters = {}
    if request.args.get("subject_kind"):
        filters["subject_kind"] = request.args["subject_kind"]
    if request.args.get("subject_id"):
        filters["subject_id"] = request.args["subject_id"]
    rows, total = db.query("audit_logs", filters=filters,
                           limit=limit, offset=offset)
    return success_list([audit_log_view(r) for r in rows], total, limit, offset)


@bp.route("/external-events", methods=["GET"])
def list_external_events():
    require_role("ProjectManager")
    limit, offset = parse_pagination(request.args)
    filters = {}
    if request.args.get("target_system"):
        filters["target_system"] = request.args["target_system"]
    rows, total = db.query("external_events", filters=filters,
                           limit=limit, offset=offset)
    return success_list([external_event_view(r) for r in rows], total, limit, offset)
