"""Audit log and escrow ledger read endpoints."""

from flask import Blueprint, g, request

from db import DB, LOCK
from errors import forbidden, not_found
from middleware import require_roles
from response import success_array
from services.common import paginate, parse_pagination
from services.serializers import audit_view, escrow_view


bp = Blueprint("audit", __name__)


@bp.route("/audit-log", methods=["GET"])
@require_roles("PlatformAdmin")
def list_audit():
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    event_type = request.args.get("event_type")
    with LOCK:
        items = list(DB.audit_log)
        if subject_type:
            items = [e for e in items if e["subject_type"] == subject_type]
        if subject_id:
            items = [e for e in items if e["subject_id"] == subject_id]
        if event_type:
            items = [e for e in items if e["event_type"] == event_type]
        items.sort(key=lambda e: e["created_at"])
        page, total, has_more = paginate(items, limit, offset)
        return success_array([audit_view(e) for e in page], limit=limit, offset=offset,
                             total_count=total, has_more=has_more)


@bp.route("/projects/<project_id>/escrow-ledger", methods=["GET"])
@require_roles("Initiator", "PlatformAdmin")
def list_escrow(project_id):
    limit, offset = parse_pagination()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        if g.role == "Initiator" and project["initiator_id"] != g.user_id:
            raise forbidden()
        items = [e for e in DB.escrow_ledger if e["project_id"] == project_id]
        items.sort(key=lambda e: e["created_at"])
        page, total, has_more = paginate(items, limit, offset)
        return success_array([escrow_view(e) for e in page], limit=limit, offset=offset,
                             total_count=total, has_more=has_more)
