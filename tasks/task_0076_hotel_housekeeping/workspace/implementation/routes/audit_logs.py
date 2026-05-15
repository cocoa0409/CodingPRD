"""Routes for /audit-logs."""

from flask import Blueprint, request

from db import DB
from middleware import auth_required
from response import list_response
from services.pagination import parse_pagination, paginate
from services.serializers import serialize_audit_log


bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
@auth_required(["Supervisor"])
def list_audit_logs():
    limit, offset = parse_pagination()
    action_type = request.args.get("action_type")
    subject_id = request.args.get("subject_id")
    items = list(DB["audit_logs"].values())
    if action_type:
        items = [a for a in items if a["action_type"] == action_type]
    if subject_id:
        items = [a for a in items if a.get("subject_id") == subject_id]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_audit_log(a) for a in page], total, limit, offset
    )
