"""Project endpoints (PRD 3.2, 3.5, 3.8)."""

from decimal import Decimal

from flask import Blueprint, g

import db
from errors import (
    ApiError, ERR_CONTRACTOR_NOT_ACTIVE, ERR_CONTRACTOR_NOT_FOUND,
    ERR_CONTRACTOR_REQUIRED, ERR_INSTALL_WINDOW_NOT_STARTED,
    ERR_MODEL_DISCONTINUED, ERR_MODEL_DOES_NOT_FIT,
    ERR_NOT_LEAD_INSTALLER, ERR_PERMIT_EXPIRED_FOR_INSTALL,
    ERR_PRODUCT_MODEL_NOT_FOUND, ERR_PROJECT_NOT_FOUND,
    ERR_PROJECT_STATE_FORBIDS, ERR_SERIAL_NUMBER_TAKEN,
    ERR_STALE_PROJECT_VERSION, ERR_SURVEY_INFEASIBLE,
    ERR_SURVEY_NOT_COMPLETED, ERR_SURVEY_NOT_FOUND,
    ERR_TECHNICIAN_NOT_ACTIVE, ERR_TECHNICIAN_NOT_CERTIFIED,
    ERR_TECHNICIAN_NOT_FOUND, ERR_UNIT_NOT_FOUND, ERR_UNIT_PROJECT_IN_PROGRESS,
    ERR_UNIT_STATE_FORBIDS, ERR_PROPERTY_NOT_FOUND, invalid_request,
    state_forbids,
)
from middleware import INSTALLER, PROJECT_COORDINATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc, cascade
from util import dec, get_json_body, money, serialize, validate_body

bp = Blueprint("projects", __name__)

PROJECT_TYPES = ["NEW_INSTALLATION", "MODERNIZATION"]

CREATE_SPEC = {
    "property_id": ("string", True, None),
    "survey_id": ("string", True, None),
    "project_type": ("enum", True, PROJECT_TYPES),
    "modernize_unit_id": ("string", False, None),
}

PATCH_SPEC = {
    "product_model_id": ("string", False, None),
    "lead_installer_technician_id": ("string", False, None),
    "contractor_id": ("string", False, None),
    "expected_project_version": ("int", True, None),
}

SCHEDULE_SPEC = {
    "install_start_date": ("datetime", True, None),
    "install_end_date": ("datetime", True, None),
}

COMPLETE_SPEC = {
    "serial_number": ("string", True, None),
}

CET_LEVEL = ("CET", "CET_AND_QEI")


def recompute_posture(project):
    apps = [a for a in db.grant_applications.values() if a["project_id"] == project["id"]]
    project["funding_posture"] = calc.funding_posture(project, apps)


def recompute_running_balance(project):
    """Before close: homeowner_balance = contract_price + approved COs - disbursed."""
    if project["contract_price"] is None:
        project["homeowner_balance"] = None
    else:
        project["homeowner_balance"] = money(
            dec(project["contract_price"])
            + dec(project["approved_change_order_total"])
            - dec(project["disbursed_grants"])
        )


@bp.post("/api/projects")
@require_roles(PROJECT_COORDINATOR)
def create_project():
    body = get_json_body()
    vals = validate_body(body, CREATE_SPEC)
    project_type = vals["project_type"]
    if project_type == "MODERNIZATION" and "modernize_unit_id" not in vals:
        raise invalid_request("modernize_unit_id is required when project_type is MODERNIZATION")
    if project_type == "NEW_INSTALLATION" and "modernize_unit_id" in vals:
        raise invalid_request("modernize_unit_id is forbidden when project_type is NEW_INSTALLATION")
    # body foreign keys (priority 4)
    get_or_404(db.properties, vals["property_id"], ERR_PROPERTY_NOT_FOUND, "Property")
    survey = get_or_404(db.surveys, vals["survey_id"], ERR_SURVEY_NOT_FOUND, "Survey")
    target_unit = None
    if project_type == "MODERNIZATION":
        target_unit = get_or_404(db.units, vals["modernize_unit_id"], ERR_UNIT_NOT_FOUND, "Unit")
        # state admission (priority 5): target unit must be IN_SERVICE / OUT_OF_SERVICE
        if target_unit["equipment_status"] not in ("IN_SERVICE", "OUT_OF_SERVICE"):
            raise state_forbids(ERR_UNIT_STATE_FORBIDS, "Unit")
    # referenced-entity status (priority 8): survey COMPLETED, verdict not INFEASIBLE
    if survey["status"] != "COMPLETED":
        raise ApiError(ERR_SURVEY_NOT_COMPLETED, 409, "Referenced survey is not COMPLETED")
    if survey["feasibility_verdict"] == "INFEASIBLE":
        raise ApiError(ERR_SURVEY_INFEASIBLE, 422, "Survey verdict is INFEASIBLE")
    # uniqueness (priority 9): one in-flight modernization per unit
    if target_unit is not None:
        for p in db.projects.values():
            if (
                p.get("modernize_unit_id") == target_unit["id"]
                and p["project_type"] == "MODERNIZATION"
                and p["status"] not in ("CLOSED", "CANCELLED")
            ):
                raise ApiError(ERR_UNIT_PROJECT_IN_PROGRESS, 409, "Unit already has a non-terminal modernization project")
    rec = db.new_record({
        "property_id": vals["property_id"],
        "survey_id": vals["survey_id"],
        "project_type": project_type,
        "modernize_unit_id": vals.get("modernize_unit_id"),
        "product_model_id": None,
        "lead_installer_technician_id": None,
        "contractor_id": None,
        "requires_structural": False,
        "structural_estimate": None,
        "contract_price": None,
        "approved_change_order_total": money(0),
        "structural_adjustment": None,
        "final_invoice": None,
        "disbursed_grants": money(0),
        "homeowner_balance": None,
        "funding_posture": "UNFUNDED",
        "install_start_date": None,
        "install_end_date": None,
        "status": "DRAFT",
    })
    db.projects[rec["id"]] = rec
    # side effect: modernization target moves UNDER_MODERNIZATION
    if target_unit is not None:
        target_unit["equipment_status"] = "UNDER_MODERNIZATION"
        db.touch(target_unit)
    return ok(serialize(rec), 201)


@bp.get("/api/projects")
@require_roles(*ALL_ROLES)
def list_projects():
    return list_endpoint(db.projects, {
        "property_id": "property_id",
        "survey_id": "survey_id",
        "product_model_id": "product_model_id",
        "lead_installer_technician_id": "lead_installer_technician_id",
        "contractor_id": "contractor_id",
        "modernize_unit_id": "modernize_unit_id",
        "status": "status",
        "project_type": "project_type",
    })


@bp.get("/api/projects/<projectId>")
@require_roles(*ALL_ROLES)
def get_project(projectId):
    rec = get_or_404(db.projects, projectId, ERR_PROJECT_NOT_FOUND, "Project")
    return ok(serialize(rec))


@bp.patch("/api/projects/<projectId>")
@require_roles(PROJECT_COORDINATOR)
def patch_project(projectId):
    project = get_or_404(db.projects, projectId, ERR_PROJECT_NOT_FOUND, "Project")
    vals = validate_body(get_json_body(), PATCH_SPEC)
    if not any(k in vals for k in ("product_model_id", "lead_installer_technician_id", "contractor_id")):
        raise invalid_request("At least one of product_model_id, lead_installer_technician_id, contractor_id is required")
    # body foreign keys (priority 4)
    model = None
    if "product_model_id" in vals:
        model = get_or_404(db.product_models, vals["product_model_id"], ERR_PRODUCT_MODEL_NOT_FOUND, "ProductModel")
    lead_tech = None
    if "lead_installer_technician_id" in vals:
        lead_tech = get_or_404(db.technicians, vals["lead_installer_technician_id"], ERR_TECHNICIAN_NOT_FOUND, "Technician")
    contractor = None
    if "contractor_id" in vals:
        contractor = get_or_404(db.contractors, vals["contractor_id"], ERR_CONTRACTOR_NOT_FOUND, "Contractor")
    # state admission (priority 5): selection only in DRAFT / QUOTED
    if project["status"] not in ("DRAFT", "QUOTED"):
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # optimistic concurrency (PRD 2.6)
    if vals["expected_project_version"] != project["version"]:
        raise ApiError(ERR_STALE_PROJECT_VERSION, 412, "Project version has advanced since the client's last read")
    # effective values after this scope update
    eff_lead = lead_tech if lead_tech is not None else (
        db.technicians.get(project["lead_installer_technician_id"]) if project["lead_installer_technician_id"] else None)
    eff_contractor = contractor if contractor is not None else (
        db.contractors.get(project["contractor_id"]) if project["contractor_id"] else None)
    # certification (priority 6): lead installer must hold CET-level certification
    if eff_lead is not None and eff_lead["certification"] not in CET_LEVEL:
        raise ApiError(ERR_TECHNICIAN_NOT_CERTIFIED, 403, "Lead installer must hold CET-level certification")
    # referenced-entity status (priority 8)
    survey = db.surveys.get(project["survey_id"])
    if survey is None or survey["status"] != "COMPLETED":
        raise ApiError(ERR_SURVEY_NOT_COMPLETED, 409, "Project survey is not COMPLETED")
    if model is not None and model["status"] != "ACTIVE":
        raise ApiError(ERR_MODEL_DISCONTINUED, 409, "Referenced product model is DISCONTINUED")
    if eff_lead is not None and eff_lead["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, 409, "Lead installer technician is INACTIVE")
    if eff_contractor is not None and eff_contractor["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACTOR_NOT_ACTIVE, 409, "Referenced contractor is SUSPENDED")
    # product selection / supersession: fit checks before any mutation (atomicity)
    quote = None
    if model is not None:
        if eff_lead is None:
            raise invalid_request("lead_installer_technician_id must be present for a selection")
        quote = calc.installation_price_quote(model, survey)
        if quote is None:
            raise ApiError(ERR_MODEL_DOES_NOT_FIT, 422, "Selected model's pit/overhead shortfall exceeds 12 inches")
        if quote[0] and eff_contractor is None:
            raise ApiError(ERR_CONTRACTOR_REQUIRED, 422, "requires_structural is true but no contractor_id supplied")
    # --- all checks passed; apply ---
    if lead_tech is not None:
        project["lead_installer_technician_id"] = lead_tech["id"]
    if contractor is not None:
        project["contractor_id"] = contractor["id"]
    if model is not None:
        requires_structural, structural_estimate, contract_price = quote
        project["product_model_id"] = model["id"]
        project["requires_structural"] = requires_structural
        project["structural_estimate"] = structural_estimate
        project["contract_price"] = contract_price
        if project["status"] == "DRAFT":
            project["status"] = "QUOTED"
    recompute_running_balance(project)
    recompute_posture(project)
    db.touch(project)
    return ok(serialize(project))


@bp.post("/api/projects/<projectId>/schedule-installation")
@require_roles(PROJECT_COORDINATOR)
def schedule_installation(projectId):
    project = get_or_404(db.projects, projectId, ERR_PROJECT_NOT_FOUND, "Project")
    vals = validate_body(get_json_body(), SCHEDULE_SPEC)
    if project["status"] != "READY_FOR_INSTALL":
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # temporal gates (priority 10)
    if vals["install_end_date"] <= vals["install_start_date"]:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "install_end_date must be strictly after install_start_date")
    permit = _current_approved_permit(project["id"])
    if permit is None or permit["valid_through"] < db.now():
        raise ApiError(ERR_PERMIT_EXPIRED_FOR_INSTALL, 409, "Install scheduling requires an APPROVED permit still within its validity window")
    project["install_start_date"] = vals["install_start_date"]
    project["install_end_date"] = vals["install_end_date"]
    project["status"] = "INSTALL_SCHEDULED"
    db.touch(project)
    return ok(serialize(project))


def _current_approved_permit(project_id):
    approved = [p for p in db.permits.values() if p["project_id"] == project_id and p["status"] == "APPROVED"]
    if not approved:
        return None
    approved.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return approved[-1]


@bp.post("/api/projects/<projectId>/complete-installation")
@require_roles(INSTALLER)
def complete_installation(projectId):
    project = get_or_404(db.projects, projectId, ERR_PROJECT_NOT_FOUND, "Project")
    vals = validate_body(get_json_body(), COMPLETE_SPEC)
    if project["status"] != "INSTALL_SCHEDULED":
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # identity binding (priority 7): caller must be the lead installer of record
    if g.user_id != project["lead_installer_technician_id"]:
        raise ApiError(ERR_NOT_LEAD_INSTALLER, 403, "Caller is not the project's lead installer")
    # uniqueness (priority 9): serial number unique across all units
    if any(u["serial_number"] == vals["serial_number"] for u in db.units.values()):
        raise ApiError(ERR_SERIAL_NUMBER_TAKEN, 409, "serial_number already exists on another unit")
    # temporal (priority 10): clock must have reached the install window start
    if db.now() < project["install_start_date"]:
        raise ApiError(ERR_INSTALL_WINDOW_NOT_STARTED, 409, "Installation window has not started")
    unit = db.new_record({
        "property_id": project["property_id"],
        "project_id": project["id"],
        "product_model_id": project["product_model_id"],
        "modernized_from_unit_id": project["modernize_unit_id"] if project["project_type"] == "MODERNIZATION" else None,
        "serial_number": vals["serial_number"],
        "install_date": db.now(),
        "equipment_status": "INSTALLED",
        "registration_status": "UNREGISTERED",
    })
    db.units[unit["id"]] = unit
    project["status"] = "INSTALL_COMPLETE"
    db.touch(project)
    return ok(serialize(project))


@bp.post("/api/projects/<projectId>/cancel")
@require_roles(PROJECT_COORDINATOR)
def cancel_project(projectId):
    project = get_or_404(db.projects, projectId, ERR_PROJECT_NOT_FOUND, "Project")
    # a REGISTERED project can never be cancelled; CLOSED/CANCELLED are terminal
    if project["status"] in ("CLOSED", "CANCELLED", "REGISTERED"):
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    cascade.cancel_project_cascade(project)
    project["status"] = "CANCELLED"
    db.touch(project)
    return ok(serialize(project))


@bp.post("/api/projects/<projectId>/close")
@require_roles(PROJECT_COORDINATOR)
def close_project(projectId):
    project = get_or_404(db.projects, projectId, ERR_PROJECT_NOT_FOUND, "Project")
    if project["status"] != "REGISTERED":
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # final_invoice = contract_price + sum(effective_amount over APPROVED COs) + structural_adjustment
    approved_cos = [c for c in db.change_orders.values() if c["project_id"] == project["id"] and c["status"] == "APPROVED"]
    co_total = sum((dec(c["effective_amount"]) for c in approved_cos), Decimal("0"))
    adjustment = Decimal("0")
    if project["requires_structural"]:
        verified = [w for w in db.work_orders.values() if w["project_id"] == project["id"] and w["status"] == "VERIFIED"]
        if verified:
            verified.sort(key=lambda w: (w["created_at"], w["_seq"]))
            adjustment = dec(calc.structural_adjustment(verified[-1]["actual_cost"], project["structural_estimate"]))
    project["structural_adjustment"] = money(adjustment)
    project["final_invoice"] = money(dec(project["contract_price"]) + co_total + dec(project["structural_adjustment"]))
    # grant disbursement waterfall over APPROVED applications
    apps = [a for a in db.grant_applications.values() if a["project_id"] == project["id"]]
    disbursed_total, balance, disbursed_apps = calc.grant_disbursement_waterfall(project, apps)
    for app in disbursed_apps:
        db.touch(app)
    project["disbursed_grants"] = disbursed_total
    project["homeowner_balance"] = balance
    recompute_posture(project)
    project["status"] = "CLOSED"
    db.touch(project)
    return ok(serialize(project))
