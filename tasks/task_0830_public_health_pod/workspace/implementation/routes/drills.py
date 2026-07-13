from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_fields, require_enum, require_type,
    sorted_by_created, strip_internal, touch,
)
from middleware import require_role
from response import success_array, success_object
from services import recompute_readiness_score

bp = Blueprint("drills", __name__)

DRILL_TYPES = {"TABLETOP", "FUNCTIONAL", "FULL_SCALE"}
READ_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "ClinicalLead"]


@bp.route("/drills", methods=["POST"])
@require_role("PublicHealthAdmin")
def create_drill():
    body = get_json_body()
    require_fields(body, ["hazard_plan_id", "drill_type", "scheduled_at"])
    fetch_or_404(db.hazard_plans, body["hazard_plan_id"], "HazardPlan")
    require_type(body["drill_type"], str, "drill_type")
    require_enum(body["drill_type"], DRILL_TYPES, "drill_type")
    require_type(body["scheduled_at"], str, "scheduled_at")

    row = new_common_fields()
    row.update({
        "hazard_plan_id": body["hazard_plan_id"],
        "drill_type": body["drill_type"],
        "scheduled_at": body["scheduled_at"],
        "status": "SCHEDULED",
        "finding": None,
        "corrective_action": None,
        "corrective_action_status": "NONE",
    })
    db.drills[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/drills/<drill_id>", methods=["GET"])
@require_role(*READ_ROLES)
def get_drill(drill_id):
    row = fetch_or_404(db.drills, drill_id, "Drill")
    return success_object(strip_internal(row))


@bp.route("/drills", methods=["GET"])
@require_role(*READ_ROLES)
def list_drills():
    limit, offset = parse_pagination(request.args)
    hazard_plan_id = request.args.get("hazard_plan_id")
    status = request.args.get("status")
    rows = list(db.drills.values())
    if hazard_plan_id:
        rows = [r for r in rows if r["hazard_plan_id"] == hazard_plan_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/drills/<drill_id>/complete", methods=["POST"])
@require_role("PublicHealthAdmin")
def complete_drill(drill_id):
    drill = fetch_or_404(db.drills, drill_id, "Drill")
    if drill["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Drill must be SCHEDULED to complete.", 409)
    body = get_json_body()
    finding = body.get("finding")
    corrective_action = body.get("corrective_action")
    drill["status"] = "COMPLETED"
    if finding is not None:
        drill["finding"] = finding
    if corrective_action:
        drill["corrective_action"] = corrective_action
        drill["corrective_action_status"] = "OPEN"
    touch(drill)

    plan = db.hazard_plans.get(drill["hazard_plan_id"])
    if plan is not None:
        recompute_readiness_score(plan, db.drills)

    return success_object(strip_internal(drill))


@bp.route("/drills/<drill_id>/cancel", methods=["POST"])
@require_role("PublicHealthAdmin")
def cancel_drill(drill_id):
    drill = fetch_or_404(db.drills, drill_id, "Drill")
    if drill["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Drill must be SCHEDULED to cancel.", 409)
    drill["status"] = "CANCELLED"
    touch(drill)
    return success_object(strip_internal(drill))


@bp.route("/drills/<drill_id>/close_corrective_action", methods=["POST"])
@require_role("PublicHealthAdmin")
def close_corrective_action(drill_id):
    drill = fetch_or_404(db.drills, drill_id, "Drill")
    if drill["status"] != "COMPLETED" or drill["corrective_action_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Drill must be COMPLETED with corrective_action_status OPEN.", 409)
    drill["corrective_action_status"] = "CLOSED"
    touch(drill)

    plan = db.hazard_plans.get(drill["hazard_plan_id"])
    if plan is not None:
        recompute_readiness_score(plan, db.drills)

    return success_object(strip_internal(drill))
