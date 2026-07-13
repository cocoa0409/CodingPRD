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
from timeutil import current_clock, format_iso8601

bp = Blueprint("hazard_plans", __name__)

HAZARD_TYPES = {
    "PANDEMIC_INFLUENZA", "BIOTERRORISM_ANTHRAX", "RADIOLOGICAL_INCIDENT",
    "CHEMICAL_RELEASE", "NATURAL_DISASTER", "OUTBREAK_OTHER",
}

ALL_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner", "ClinicalLead", "Volunteer"]


@bp.route("/hazard-plans", methods=["POST"])
@require_role("PublicHealthAdmin")
def create_hazard_plan():
    body = get_json_body()
    require_fields(body, ["hazard_type", "title", "jurisdiction_code", "target_population"])
    require_type(body["hazard_type"], str, "hazard_type")
    require_enum(body["hazard_type"], HAZARD_TYPES, "hazard_type")
    require_type(body["title"], str, "title")
    require_type(body["jurisdiction_code"], str, "jurisdiction_code")
    require_type(body["target_population"], int, "target_population")
    if body["target_population"] < 0:
        raise ApiError("ERR_VALIDATION", "target_population must be >= 0.", 400)

    row = new_common_fields()
    row.update({
        "hazard_type": body["hazard_type"],
        "title": body["title"],
        "jurisdiction_code": body["jurisdiction_code"],
        "target_population": body["target_population"],
        "status": "DRAFT",
        "activated_at": None,
        "stood_down_at": None,
        "readiness_score": 0,
    })
    db.hazard_plans[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/hazard-plans/<plan_id>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_hazard_plan(plan_id):
    row = fetch_or_404(db.hazard_plans, plan_id, "HazardPlan")
    return success_object(strip_internal(row))


@bp.route("/hazard-plans", methods=["GET"])
@require_role(*ALL_ROLES)
def list_hazard_plans():
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    rows = list(db.hazard_plans.values())
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/hazard-plans/<plan_id>/activate", methods=["POST"])
@require_role("PublicHealthAdmin")
def activate_hazard_plan(plan_id):
    row = fetch_or_404(db.hazard_plans, plan_id, "HazardPlan")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "HazardPlan must be DRAFT to activate.", 409)
    row["status"] = "ACTIVATED"
    row["activated_at"] = format_iso8601(current_clock())
    touch(row)
    return success_object(strip_internal(row))


@bp.route("/hazard-plans/<plan_id>/stand_down", methods=["POST"])
@require_role("PublicHealthAdmin")
def stand_down_hazard_plan(plan_id):
    row = fetch_or_404(db.hazard_plans, plan_id, "HazardPlan")
    if row["status"] != "ACTIVATED":
        raise ApiError("ERR_INVALID_STATE", "HazardPlan must be ACTIVATED to stand down.", 409)
    child_pods = [p for p in db.pods.values() if p["hazard_plan_id"] == plan_id]
    if any(p["operational_status"] != "CLOSED" for p in child_pods):
        raise ApiError("ERR_POD_NOT_READY_FOR_STAND_DOWN", "Every POD under this plan must be CLOSED first.", 409)
    row["status"] = "STOOD_DOWN"
    row["stood_down_at"] = format_iso8601(current_clock())
    touch(row)
    return success_object(strip_internal(row))
