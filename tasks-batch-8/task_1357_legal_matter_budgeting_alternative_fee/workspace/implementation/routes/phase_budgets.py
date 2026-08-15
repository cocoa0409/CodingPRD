"""PhaseBudget endpoints (PRD §3.3)."""
from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_NOT_OPEN,
    ERR_PHASE_HAS_ACTUALS,
    ERR_PHASE_HAS_PENDING_AMENDMENT,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("phase_budgets", __name__)

LITIGATION_STAGES = {"INTAKE", "PLEADINGS", "DISCOVERY", "PRETRIAL", "TRIAL", "APPEAL"}
READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner", "ManagingPartner")


@bp.post("/firms/<firmId>/matters/<matterId>/phase_budgets")
def create_phase_budget(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst", "BillingPartner")
    matter = util.get_matter_scoped(firmId, matterId)
    data = util.body()
    util.require_fields(data, ["litigation_stage", "task_code", "original_budget_cents"])
    stage = util.check_enum(data, "litigation_stage", LITIGATION_STAGES)
    task_code = util.check_string(data, "task_code")
    original = util.check_int(data, "original_budget_cents")
    etc = data.get("etc_cents")
    if etc is None:
        etc = 0
    else:
        etc = util.check_int(data, "etc_cents", minimum=0)

    phase = util.new_resource()
    phase.update({
        "matter_id": matter["id"],
        "firm_id": firmId,
        "litigation_stage": stage,
        "task_code": task_code,
        "original_budget_cents": original,
        "current_budget_cents": original,
        "actual_to_date_cents": 0,
        "etc_cents": etc,
        "status": "DRAFT",
        "version_in_force": 1,
    })
    db.phase_budgets[phase["id"]] = phase
    return success_object(phase, 201)


@bp.get("/firms/phase_budgets/<phaseBudgetId>")
def get_phase_budget(phaseBudgetId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    phase = util.get_phase_flat(phaseBudgetId)
    derived.recompute_phase_actuals(phase["matter_id"])
    return success_object(phase, 200)


@bp.get("/firms/phase_budgets")
def list_phase_budgets():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters(["firm_id", "matter_id", "status", "litigation_stage", "task_code"])
    items = util.apply_filters(list(db.phase_budgets.values()), filters)
    for p in items:
        derived.recompute_phase_actuals(p["matter_id"])
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/phase_budgets")
def list_phase_budgets_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    derived.recompute_phase_actuals(matterId)
    filters = util.query_filters(["status", "litigation_stage"])
    items = [p for p in db.phase_budgets.values() if p.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/phase_budgets/<phaseBudgetId>/activate")
def activate_phase_budget(firmId, phaseBudgetId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst", "BillingPartner")
    phase = util.get_phase_scoped(firmId, phaseBudgetId)
    if phase["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT phase budget can be activated", 409)
    matter = db.matters.get(phase["matter_id"])
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")
    if matter["status"] not in ("OPEN", "ACTIVE", "REOPENED"):
        raise ApiError(ERR_MATTER_NOT_OPEN,
                       "Matter not in OPEN/ACTIVE/REOPENED for phase activation", 409)
    if int(phase.get("original_budget_cents", 0)) <= 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "original_budget_cents must be positive", 400)
    phase["status"] = "ACTIVE"
    util.touch(phase)
    derived.recompute_matter(matter)
    return success_object(phase, 200)


@bp.post("/firms/<firmId>/phase_budgets/<phaseBudgetId>/void")
def void_phase_budget(firmId, phaseBudgetId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    phase = util.get_phase_scoped(firmId, phaseBudgetId)
    if phase["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT or ACTIVE phase budget can be voided", 409)
    matter = db.matters.get(phase["matter_id"])
    if phase["status"] == "ACTIVE":
        # Guards in order: actuals first, then pending amendments (PRD §3.3).
        derived.recompute_phase_actuals(phase["matter_id"])
        if int(phase.get("actual_to_date_cents", 0)) != 0:
            raise ApiError(ERR_PHASE_HAS_ACTUALS,
                           "Cannot void PhaseBudget with actual_to_date_cents > 0", 409)
        pending = [
            a for a in db.budget_amendments.values()
            if a.get("phase_budget_id") == phase["id"]
            and a.get("status") in ("DRAFT", "PENDING_REVIEW")
        ]
        if pending:
            raise ApiError(ERR_PHASE_HAS_PENDING_AMENDMENT,
                           "Cannot void PhaseBudget with DRAFT/PENDING_REVIEW amendment", 409)
    phase["status"] = "VOIDED"
    util.touch(phase)
    if matter is not None:
        derived.recompute_matter(matter)
    return success_object(phase, 200)


@bp.patch("/firms/phase_budgets/<phaseBudgetId>")
def update_phase_budget(phaseBudgetId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst", "BillingPartner")
    phase = util.get_phase_flat(phaseBudgetId)
    data = util.body()
    if "etc_cents" not in data or data.get("etc_cents") is None:
        raise ApiError(ERR_INVALID_REQUEST, "etc_cents is required", 400)
    etc = util.check_int(data, "etc_cents", minimum=0)
    phase["etc_cents"] = etc
    util.touch(phase)
    matter = db.matters.get(phase["matter_id"])
    if matter is not None:
        derived.recompute_matter(matter)
    return success_object(phase, 200)
