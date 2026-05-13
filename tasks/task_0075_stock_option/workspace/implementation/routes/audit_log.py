"""Audit log query routes."""

from flask import Blueprint, request
from db import DB
from middleware import auth_required
from response import list_response
from services.common import (
    get_or_404, get_pagination, paginate_list, sort_by_created_at_asc,
)
from services.serializers import serialize_audit


bp = Blueprint("audit_log", __name__)


@bp.get("/option-plans/<plan_id>/audit-log")
@auth_required(["PlanAdministrator", "AuditViewer"])
def list_audit(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    items = [a for a in DB["audit_log"].values() if a.get("plan_id") == plan_id]
    action_code = request.args.get("action_code")
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")
    if action_code:
        items = [a for a in items if a["action_code"] == action_code]
    if target_entity:
        items = [a for a in items if a["target_entity"] == target_entity]
    if target_id:
        items = [a for a in items if a["target_id"] == target_id]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_audit(a) for a in sliced], total, limit, offset)
