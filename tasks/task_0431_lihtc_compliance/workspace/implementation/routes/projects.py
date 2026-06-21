"""Project endpoints (PRD §3.1, §3.7)."""

from flask import Blueprint, request

import errors
import middleware
import response
import serializers
import validate
from db import db, new_id, stamp_create, touch
from services import domain

bp = Blueprint("projects", __name__)

MINIMUM_SET_ASIDE = {"TWENTY_FIFTY", "FORTY_SIXTY", "AVERAGE_INCOME"}


@bp.route("/projects", methods=["POST"])
def create_project():
    middleware.require_role("OwnerAgent")
    body = validate.get_json_body()
    name = validate.as_str(body, "name")
    ami = validate.as_int(body, "area_median_income_cents", minimum=100000)
    minimum_set_aside = validate.as_enum(body, "minimum_set_aside", MINIMUM_SET_ASIDE)
    placed = validate.as_datetime(body, "placed_in_service_date")

    project = {
        "id": new_id(),
        "name": name,
        "area_median_income_cents": ami,
        "minimum_set_aside": minimum_set_aside,
        "placed_in_service_date": placed,
        "status": "DRAFT",
        "posture": "COMPLIANT",
        "open_finding_count": 0,
    }
    stamp_create(project)
    db.projects[project["id"]] = project
    return response.success(serializers.public(project), status=201)


@bp.route("/projects", methods=["GET"])
def list_projects():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    items = serializers.sort_by_created(list(db.projects.values()))
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    middleware.require_role("OwnerAgent", "StateHFA")
    project = db.projects.get(pid)
    if project is None:
        raise errors.not_found("Project not found")
    return response.success(serializers.public(project), status=200)


@bp.route("/projects/<pid>/certify-set-aside", methods=["POST"])
def certify_set_aside(pid):
    middleware.require_role("StateHFA")
    project = db.projects.get(pid)
    if project is None:
        raise errors.not_found("Project not found")
    if project["status"] != "DRAFT":
        raise errors.invalid_state("Project must be DRAFT to certify set-aside")

    from services import calc
    all_units = domain.units_for_project(pid)
    total_units = sum(b["total_residential_units"] for b in domain.buildings_for_project(pid))
    if not calc.minimum_set_aside_satisfied(project["minimum_set_aside"], all_units, total_units):
        raise errors.ApiError(errors.ERR_SET_ASIDE_NOT_MET, 409, "Minimum set-aside test not satisfied")

    project["status"] = "SET_ASIDE_MET"
    touch(project)
    domain.recompute_project_posture(project)
    return response.success(serializers.public(project), status=200)


@bp.route("/projects/<pid>/begin-credit-period", methods=["POST"])
def begin_credit_period(pid):
    middleware.require_role("StateHFA")
    project = db.projects.get(pid)
    if project is None:
        raise errors.not_found("Project not found")
    if project["status"] != "SET_ASIDE_MET":
        raise errors.invalid_state("Project must be SET_ASIDE_MET")
    has_final = any(
        b["credit_status"] == "FINAL_8609" for b in domain.buildings_for_project(pid)
    )
    if not has_final:
        raise errors.invalid_state("At least one building must be FINAL_8609")
    project["status"] = "CREDIT_PERIOD"
    touch(project)
    return response.success(serializers.public(project), status=200)


@bp.route("/projects/<pid>/begin-compliance-period", methods=["POST"])
def begin_compliance_period(pid):
    middleware.require_role("StateHFA")
    project = db.projects.get(pid)
    if project is None:
        raise errors.not_found("Project not found")
    if project["status"] != "CREDIT_PERIOD":
        raise errors.invalid_state("Project must be CREDIT_PERIOD")
    project["status"] = "COMPLIANCE_PERIOD"
    touch(project)
    return response.success(serializers.public(project), status=200)


@bp.route("/projects/<pid>/close", methods=["POST"])
def close_project(pid):
    middleware.require_role("StateHFA")
    project = db.projects.get(pid)
    if project is None:
        raise errors.not_found("Project not found")
    if project["status"] != "COMPLIANCE_PERIOD":
        raise errors.invalid_state("Project must be COMPLIANCE_PERIOD to close")
    if project["open_finding_count"] != 0:
        raise errors.ApiError(
            errors.ERR_OPEN_FINDINGS_BLOCK_CLOSE, 409,
            "Project cannot close while findings are unresolved",
        )
    project["status"] = "CLOSED"
    touch(project)
    return response.success(serializers.public(project), status=200)
