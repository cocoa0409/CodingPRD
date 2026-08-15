"""Project lifecycle endpoints: create, list, get, cancel, close-punch-list,
complete (PRD 3.1, 3.8, 3.9)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CREDIT_LIMIT_EXCEEDED,  # noqa: F401  (catalog reference)
    ERR_HEALTH_PERMIT_NOT_APPROVED,
    ERR_INVALID_REQUEST,
    ERR_OPEN_BLOCKING_PUNCH_ITEMS,
    ERR_OPEN_SERVICE_ASSIGNMENT,
    ERR_PROJECT_ALREADY_TERMINAL,
    ERR_PROJECT_NOT_COMMISSIONED,
    ERR_PROJECT_NOT_PUNCH_CLOSED,
    ERR_STALE_PROJECT_VERSION,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import (
    check_project_ownership,
    paginate,
    resolve_customer,
    resolve_project,
    serialize,
)
from services import workflow
from services.validate import json_body, opt_number, req_enum, req_str

bp = Blueprint("projects", __name__)

JURISDICTIONS = ("CITY_HEALTH", "COUNTY_HEALTH", "STATE_HEALTH")


def _expected_version(body: dict) -> int:
    v = body.get("expected_project_version")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "expected_project_version is required and must be an integer",
        )
    return v


@bp.route("/design-build-projects", methods=["POST"])
@require_roles("ProjectManager")
def create_project(_user_id=None, _role=None):
    body = json_body(required=True)
    customer_id = req_str(body, "customer_id")
    project_name = req_str(body, "project_name")
    site_address = req_str(body, "site_address")
    jurisdiction = req_enum(body, "health_jurisdiction", JURISDICTIONS)
    retainage_pct = opt_number(body, "retainage_pct", default=0.10)
    # Body FK must resolve to a live record.
    resolve_customer(customer_id)
    if not (retainage_pct > 0 and retainage_pct <= 0.20):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "retainage_pct must be greater than 0 and at most 0.20",
        )
    project = db.stamp_new({
        "customer_id": customer_id,
        "project_name": project_name,
        "site_address": site_address,
        "health_jurisdiction": jurisdiction,
        "quote_baseline_cents": 0,
        "retainage_pct": retainage_pct,
        "retainage_held_cents": 0,
        "warranty_registered_count": 0,
        "status": "DESIGN",
    })
    db.projects[project["id"]] = project
    return success_object(serialize(project), 201)


@bp.route("/design-build-projects", methods=["GET"])
@require_roles("PlatformAdmin", "ProjectManager", "SalesRep", "KitchenDesigner", "Customer")
def list_projects(_user_id=None, _role=None):
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    records = list(db.projects.values())
    if _role == "Customer":
        records = [p for p in records if p["customer_id"] == _user_id]
    if customer_id is not None:
        records = [p for p in records if p["customer_id"] == customer_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paginate(records)


@bp.route("/design-build-projects/<id>", methods=["GET"])
@require_roles(
    "PlatformAdmin", "ProjectManager", "SalesRep", "KitchenDesigner", "Customer",
    "PermitCoordinator", "LogisticsCoordinator", "FabricationLead",
    "StartupTechnician", "ServiceManager",
)
def get_project(id, _user_id=None, _role=None):
    project = resolve_project(id)
    check_project_ownership(_user_id, _role, project)
    return success_object(serialize(project), 200)


@bp.route("/design-build-projects/<id>/cancel", methods=["POST"])
@require_roles("ProjectManager")
def cancel_project(id, _user_id=None, _role=None):
    project = resolve_project(id)
    if project["status"] not in workflow.PROJECT_CANCELLABLE:
        raise ApiError(
            ERR_PROJECT_ALREADY_TERMINAL,
            HTTP_STATUS[ERR_PROJECT_ALREADY_TERMINAL],
            "Project is already terminal",
        )
    customer = db.customers.get(project["customer_id"])
    workflow.cancel_project(project, customer)
    return success_object(serialize(project), 200)


@bp.route("/design-build-projects/<id>/close-punch-list", methods=["POST"])
@require_roles("ProjectManager")
def close_punch_list(id, _user_id=None, _role=None):
    project = resolve_project(id)
    body = json_body(required=True)
    expected = _expected_version(body)
    # State guard.
    if project["status"] != "COMMISSIONED":
        raise ApiError(
            ERR_PROJECT_NOT_COMMISSIONED,
            HTTP_STATUS[ERR_PROJECT_NOT_COMMISSIONED],
            "Punch-list close requires Project in COMMISSIONED",
        )
    # No OPEN FUNCTIONAL / LIFE_SAFETY punch items.
    for p in db.punch_items.values():
        if (
            p["project_id"] == project["id"]
            and p["status"] == "OPEN"
            and p["severity"] in ("FUNCTIONAL", "LIFE_SAFETY")
        ):
            raise ApiError(
                ERR_OPEN_BLOCKING_PUNCH_ITEMS,
                HTTP_STATUS[ERR_OPEN_BLOCKING_PUNCH_ITEMS],
                "OPEN FUNCTIONAL or LIFE_SAFETY punch items block punch close",
            )
    # HEALTH_DEPT filing must be APPROVED.
    health_ok = any(
        f["project_id"] == project["id"]
        and f["authority"] == "HEALTH_DEPT"
        and f["status"] == "APPROVED"
        for f in db.filings.values()
    )
    if not health_ok:
        raise ApiError(
            ERR_HEALTH_PERMIT_NOT_APPROVED,
            HTTP_STATUS[ERR_HEALTH_PERMIT_NOT_APPROVED],
            "HEALTH_DEPT PermitFiling not APPROVED at punch close",
        )
    # OCC check is evaluated last, after the fiscal/business guards.
    if expected != project["version"]:
        raise ApiError(
            ERR_STALE_PROJECT_VERSION,
            HTTP_STATUS[ERR_STALE_PROJECT_VERSION],
            "expected_project_version does not match Project.version",
        )
    customer = db.customers.get(project["customer_id"])
    workflow.close_punch_list(project, customer)
    return success_object(serialize(project), 200)


@bp.route("/design-build-projects/<id>/complete", methods=["POST"])
@require_roles("ProjectManager")
def complete_project(id, _user_id=None, _role=None):
    project = resolve_project(id)
    if project["status"] != "PUNCH_CLOSED":
        raise ApiError(
            ERR_PROJECT_NOT_PUNCH_CLOSED,
            HTTP_STATUS[ERR_PROJECT_NOT_PUNCH_CLOSED],
            "Project complete requires PUNCH_CLOSED",
        )
    for a in db.assignments.values():
        if a["project_id"] == project["id"] and a["status"] == "OPEN":
            raise ApiError(
                ERR_OPEN_SERVICE_ASSIGNMENT,
                HTTP_STATUS[ERR_OPEN_SERVICE_ASSIGNMENT],
                "OPEN ServiceAssignment blocks Project completion",
            )
    customer = db.customers.get(project["customer_id"])
    workflow.complete_project(project, customer)
    return success_object(serialize(project), 200)
