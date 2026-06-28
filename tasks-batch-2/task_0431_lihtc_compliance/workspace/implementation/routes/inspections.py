"""Inspection endpoints and UPCS lifecycle (PRD §3.8)."""

from flask import Blueprint, g, request

import errors
import middleware
import response
import serializers
import validate
from db import db, new_id, stamp_create, touch
from services import calc, domain

bp = Blueprint("inspections", __name__)


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    middleware.require_role("StateHFA")
    body = validate.get_json_body()
    building_id = validate.as_str(body, "building_id")
    window_start = validate.as_datetime(body, "window_start")
    window_end = validate.as_datetime(body, "window_end")
    inspected_on = validate.as_datetime(body, "inspected_on")
    deduction_points = validate.as_int_array(body, "deduction_points", required=True)
    has_exigent = validate.as_bool(body, "has_exigent_health_safety", required=False, default=False)

    building = db.buildings.get(building_id)
    if building is None:
        raise errors.not_found("Building not found")

    # Priority 9.5: inspection-window separation (closed interval + 7-day buffer).
    new_start = domain.parse_dt(window_start)
    new_end = domain.parse_dt(window_end)
    for insp in db.inspections.values():
        if insp["building_id"] != building_id:
            continue
        e_start = domain.parse_dt(insp["window_start"])
        e_end = domain.parse_dt(insp["window_end"])
        if domain.inspection_conflicts(new_start, new_end, e_start, e_end):
            raise errors.ApiError(
                errors.ERR_INSPECTION_WINDOW_CONFLICT, 409,
                "Inspection window conflicts with an existing window on this building",
            )

    inspection = {
        "id": new_id(),
        "building_id": building_id,
        "window_start": window_start,
        "window_end": window_end,
        "inspected_on": inspected_on,
        "deduction_points": deduction_points,
        "has_exigent_health_safety": has_exigent,
        "score": None,
        "result": "PASS",
        "status": "SCHEDULED",
    }
    stamp_create(inspection)
    db.inspections[inspection["id"]] = inspection
    return response.success(serializers.public(inspection), status=201)


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    building_id = request.args.get("building_id")
    items = list(db.inspections.values())
    if building_id is not None:
        items = [i for i in items if i["building_id"] == building_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    middleware.require_role("OwnerAgent", "StateHFA")
    inspection = db.inspections.get(iid)
    if inspection is None:
        raise errors.not_found("Inspection not found")
    return response.success(serializers.public(inspection), status=200)


@bp.route("/inspections/<iid>/conduct", methods=["POST"])
def conduct_inspection(iid):
    middleware.require_role("StateHFA")
    inspection = db.inspections.get(iid)
    if inspection is None:
        raise errors.not_found("Inspection not found")
    if inspection["status"] != "SCHEDULED":
        raise errors.invalid_state("Inspection must be SCHEDULED to conduct")

    score, result = calc.inspection_score_and_result(
        inspection["deduction_points"], inspection["has_exigent_health_safety"]
    )
    inspection["score"] = score
    inspection["result"] = result
    inspection["status"] = "CONDUCTED"
    touch(inspection)

    if result == "FAIL":
        building = db.buildings.get(inspection["building_id"])
        if building is not None:
            domain.create_finding(
                project_id=building["project_id"],
                building_id=building["id"],
                inspection_id=inspection["id"],
                category="UPCS_FAIL",
                discovered_on=inspection["inspected_on"],
                origin_agent_id=g.user_id,
            )
    return response.success(serializers.public(inspection), status=200)


@bp.route("/inspections/<iid>/close", methods=["POST"])
def close_inspection(iid):
    middleware.require_role("StateHFA")
    inspection = db.inspections.get(iid)
    if inspection is None:
        raise errors.not_found("Inspection not found")
    if inspection["status"] != "CONDUCTED":
        raise errors.invalid_state("Inspection must be CONDUCTED to close")
    # Priority 12: blocked while any linked finding is OPEN or REPORTED_8823.
    for f in db.findings.values():
        if f["inspection_id"] == iid and f["status"] in ("OPEN", "REPORTED_8823"):
            raise errors.ApiError(
                errors.ERR_OPEN_FINDINGS_BLOCK_CLOSE, 409,
                "Inspection cannot close while linked findings are unresolved",
            )
    inspection["status"] = "CLOSED"
    touch(inspection)
    return response.success(serializers.public(inspection), status=200)
