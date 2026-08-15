"""RepairProject endpoints and lifecycle transitions."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BID_EMPTY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import project_ops
from services.project_ops import SURVEY_TYPES
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    fmt_dt,
    get_json_body,
    optional_int,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_date,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("projects", __name__)

READ_ROLES = (
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
)


def get_project_or_404(project_id: str) -> dict:
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")
    return project


@bp.route("/v1/repair-projects", methods=["POST"])
@require_roles("ProjectManager")
def create_project(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness.
    vessel_id = require_string(body, "vessel_id")
    dock_id = require_string(body, "dock_id")
    contract_delivery_date = require_date(body, "contract_delivery_date")
    warranty_days = optional_int(body, "warranty_days")
    if warranty_days is None:
        warranty_days = 90
    if warranty_days <= 0:
        raise_err(ERR_INVALID_REQUEST, "warranty_days must be > 0")
    change_budget_cents = optional_int(body, "change_budget_cents")
    required_survey_types = body.get("required_survey_types")
    if required_survey_types is None:
        required_survey_types = []
    if not isinstance(required_survey_types, list) or any(
        not isinstance(t, str) or t not in SURVEY_TYPES for t in required_survey_types
    ):
        raise_err(
            ERR_INVALID_REQUEST,
            "required_survey_types must be an array of declared survey types",
        )

    # Rung 4: body-referenced ids exist.
    if vessel_id not in db.vessels:
        raise_err(ERR_NOT_FOUND, "Vessel id does not exist")
    if dock_id not in db.docks:
        raise_err(ERR_NOT_FOUND, "DockBerth id does not exist")

    project = {
        "vessel_id": vessel_id,
        "dock_id": dock_id,
        "contract_delivery_date": contract_delivery_date,
        "warranty_days": warranty_days,
        "change_budget_cents": change_budget_cents,
        "required_survey_types": list(required_survey_types),
        "status": "DRAFT",
        "bid_total_cents": 0,
        "awarded_price_cents": None,
        "contracted_price_cents": None,
        "actual_dock_in_utc": None,
        "critical_path_days": 0,
        "forecast_delivery_utc": None,
        "ld_daily_rate_cents": None,
        "provisional_ld_cents": 0,
        "liquidated_damages_cents": None,
        "delivered_at_utc": None,
        "warranty_end_utc": None,
    }
    db.stamp_new(project)
    db.projects[project["id"]] = project
    return success_object(serialize(project), 201)


@bp.route("/v1/repair-projects", methods=["GET"])
@require_roles(*READ_ROLES)
def list_projects(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.projects.values()))
    items = apply_filters(items, ["vessel_id", "dock_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/v1/repair-projects/<project_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_project(project_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_project_or_404(project_id)))


@bp.route("/v1/repair-projects/<project_id>/submit-bid", methods=["POST"])
@require_roles("ProjectManager")
def submit_bid(project_id: str, _user_id: str, _role: str):
    project = get_project_or_404(project_id)
    # Rung 5: state precondition.
    if project["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "submit-bid requires the project to be DRAFT")
    # Rung 8: at least one non-cancelled BASE_SPEC line.
    base_lines = [
        w
        for w in project_ops.project_work_items(project_id)
        if w["origin_kind"] == "BASE_SPEC" and w["status"] != "CANCELLED"
    ]
    if not base_lines:
        raise_err(ERR_BID_EMPTY, "submit-bid requires a non-empty base specification")
    project["status"] = "BID_SUBMITTED"
    project_ops.refresh_project_derived(project, include_bid=True)
    db.touch(project)
    return success_object(serialize(project))


@bp.route("/v1/repair-projects/<project_id>/award", methods=["POST"])
@require_roles("CommercialApprover")
def award_project(project_id: str, _user_id: str, _role: str):
    project = get_project_or_404(project_id)
    if project["status"] != "BID_SUBMITTED":
        raise_err(ERR_INVALID_STATE, "award requires the project to be BID_SUBMITTED")
    # Freeze commercial terms and select the LD tier.
    project["status"] = "CONTRACTED"
    project["awarded_price_cents"] = project["bid_total_cents"]
    project["contracted_price_cents"] = project["awarded_price_cents"]
    project["ld_daily_rate_cents"] = project_ops.ld_tier_rate(project["contracted_price_cents"])
    # Before docking no forecast exists, so the provisional accrual is zero.
    project["provisional_ld_cents"] = project_ops.compute_provisional_ld(project)
    db.touch(project)
    return success_object(serialize(project))


@bp.route("/v1/repair-projects/<project_id>/deliver", methods=["POST"])
@require_roles("ProjectManager")
def deliver_project(project_id: str, _user_id: str, _role: str):
    project = get_project_or_404(project_id)
    if project["status"] != "WORK_COMPLETE":
        raise_err(ERR_INVALID_STATE, "deliver requires the project to be WORK_COMPLETE")
    now = db.clock_dt()
    delivered_iso = fmt_dt(now)
    project["status"] = "DELIVERED"
    project["delivered_at_utc"] = delivered_iso
    # Final LD variant, evaluated once against the actual delivery date.
    project["liquidated_damages_cents"] = project_ops.compute_liquidated_damages(
        project["contracted_price_cents"],
        project["contract_delivery_date"],
        now.date(),
    )
    project["warranty_end_utc"] = fmt_dt(now + timedelta(days=project["warranty_days"]))
    # provisional_ld_cents freezes at its last computed value.
    db.touch(project)
    return success_object(serialize(project))
