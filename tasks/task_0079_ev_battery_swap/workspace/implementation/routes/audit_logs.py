"""AuditLog list endpoint."""

from flask import Blueprint, request

from db import DB
from middleware import auth_required
from response import list_response
from services.common import get_pagination, paginate, sort_by_created_at_asc


bp = Blueprint("audit_logs", __name__, url_prefix="/swap-stations")


@bp.route("/audit-logs", methods=["GET"])
@auth_required(["PlatformAdmin"])
def list_audit_logs():
    limit, offset = get_pagination()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    event_type = request.args.get("event_type")

    items = list(DB["audit_logs"].values())
    if entity_type is not None:
        items = [r for r in items if r.get("entity_type") == entity_type]
    if entity_id is not None:
        items = [r for r in items if r.get("entity_id") == entity_id]
    if event_type is not None:
        items = [r for r in items if r.get("event_type") == event_type]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)
