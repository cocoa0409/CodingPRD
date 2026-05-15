"""ReductionProject endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import api_error
from ..response import success_envelope
from ..services.calculations import recompute_open_reports_for_period
from ..store import store, now_ts
from ..utils import (
    check_version,
    decimal_places,
    get_json_body,
    require_enum,
    require_str,
    to_decimal,
)
from ._helpers import get_org_or_404, get_project_or_404


projects_bp = Blueprint("projects", __name__)


PROJECT_TYPES = {"INTERNAL_REDUCTION", "EXTERNAL_OFFSET"}


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


@projects_bp.route("/organizations/<org_id>/projects", methods=["POST"])
@require_auth(["DataSteward"])
def create_project(org_id):
    get_org_or_404(org_id)
    body = get_json_body()
    name = require_str(body, "name", min_len=1, max_len=200)
    project_type = require_enum(body, "project_type", PROJECT_TYPES)
    facility_id = body.get("facility_id")

    if project_type == "INTERNAL_REDUCTION":
        if not isinstance(facility_id, str) or not facility_id:
            raise api_error("ERR_VALIDATION_FAILED", "facility_id required for INTERNAL_REDUCTION")
        f = store.facilities.get(facility_id)
        if not f:
            raise api_error("ERR_NOT_FOUND", "facility_id not found")
        if f.get("organization_id") != org_id:
            raise api_error("ERR_CROSS_ORG_REFERENCE", "facility_id belongs to a different organization")
    else:
        if facility_id is not None:
            raise api_error("ERR_VALIDATION_FAILED", "facility_id must be null for EXTERNAL_OFFSET")

    reduction = to_decimal(body.get("reduction_kg_co2e"), "reduction_kg_co2e")
    if reduction < 0:
        raise api_error("ERR_VALIDATION_FAILED", "reduction_kg_co2e must be >= 0")
    if decimal_places(reduction) > 4:
        raise api_error("ERR_VALIDATION_FAILED", "reduction_kg_co2e must have at most 4 decimal places")

    period_id = body.get("reporting_period_id")
    if not isinstance(period_id, str) or not period_id:
        raise api_error("ERR_VALIDATION_FAILED", "reporting_period_id is required")
    period = store.reporting_periods.get(period_id)
    if not period:
        raise api_error("ERR_NOT_FOUND", "reporting_period_id not found")
    if period.get("organization_id") != org_id:
        raise api_error("ERR_CROSS_ORG_REFERENCE", "reporting_period_id belongs to a different organization")

    payload = {
        "organization_id": org_id,
        "name": name,
        "project_type": project_type,
        "facility_id": facility_id,
        "reduction_kg_co2e": float(reduction),
        "reporting_period_id": period_id,
        "status": "PLANNED",
    }
    with store.lock:
        store.stamp_create(payload)
        store.reduction_projects[payload["id"]] = payload
    return success_envelope(payload, status=201)


@projects_bp.route("/organizations/<org_id>/projects/<project_id>/activate", methods=["POST"])
@require_auth(["DataSteward"])
def activate_project(org_id, project_id):
    get_org_or_404(org_id)
    project = get_project_or_404(org_id, project_id)
    body = get_json_body()

    if project.get("status") != "PLANNED":
        raise api_error("ERR_INVALID_STATE", "Project must be PLANNED to activate")
    check_version(body, project)

    period = store.reporting_periods.get(project["reporting_period_id"])
    if not period or period.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Parent reporting period must be OPEN")

    with store.lock:
        project["status"] = "ACTIVE"
        _bump(project)
    return success_envelope(project)


@projects_bp.route("/organizations/<org_id>/projects/<project_id>/complete", methods=["POST"])
@require_auth(["DataSteward"])
def complete_project(org_id, project_id):
    get_org_or_404(org_id)
    project = get_project_or_404(org_id, project_id)
    body = get_json_body()

    if project.get("status") != "ACTIVE":
        raise api_error("ERR_INVALID_STATE", "Project must be ACTIVE to complete")
    check_version(body, project)

    period = store.reporting_periods.get(project["reporting_period_id"])
    if not period or period.get("status") not in ("OPEN", "CLOSED"):
        raise api_error("ERR_INVALID_STATE", "Parent reporting period must be OPEN or CLOSED")

    if project["project_type"] == "EXTERNAL_OFFSET":
        for c in store.carbon_credits.values():
            if c.get("linked_reduction_project_id") == project_id and c.get("status") != "RETIRED":
                raise api_error("ERR_INVALID_STATE", "All linked credits must be RETIRED")

    with store.lock:
        project["status"] = "COMPLETED"
        _bump(project)
        # Cascade: recompute reports
        recompute_open_reports_for_period(project["reporting_period_id"])
    return success_envelope(project)


@projects_bp.route("/organizations/<org_id>/projects/<project_id>/cancel", methods=["POST"])
@require_auth(["DataSteward"])
def cancel_project(org_id, project_id):
    get_org_or_404(org_id)
    project = get_project_or_404(org_id, project_id)
    body = get_json_body()

    if project.get("status") not in ("PLANNED", "ACTIVE"):
        raise api_error("ERR_INVALID_STATE", "Only PLANNED or ACTIVE projects can be cancelled")
    check_version(body, project)

    for c in store.carbon_credits.values():
        if c.get("linked_reduction_project_id") == project_id and c.get("status") == "RETIRED":
            raise api_error("ERR_INVALID_STATE", "A RETIRED credit references this project")

    with store.lock:
        project["status"] = "CANCELLED"
        _bump(project)
    return success_envelope(project)
