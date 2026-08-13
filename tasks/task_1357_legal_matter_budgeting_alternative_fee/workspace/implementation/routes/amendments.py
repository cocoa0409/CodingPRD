"""BudgetAmendment endpoints (PRD §3.7)."""
from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_NOT_OPEN,
    ERR_PERIOD_CLOSED,
    ERR_STALE_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_AMENDMENT_NEGATIVE_BUDGET,
    ERR_AMENDMENT_AUTHORITY_EXCEEDED,
    ERR_AMENDMENT_SUPERSEDE_INVALID,
    ERR_PHASE_NOT_AMENDABLE,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("amendments", __name__)

READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner", "ManagingPartner")

# Firm-wide authority threshold (PRD §2.8 names the constant without a value).
PARTNER_AMENDMENT_AUTHORITY_CENTS = 100000


@bp.post("/firms/<firmId>/matters/<matterId>/budget_amendments")
def create_amendment(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst")
    matter = util.get_matter_scoped(firmId, matterId)
    data = util.body()
    util.require_fields(data, ["phase_budget_id", "delta_cents", "scope_change_reason"])

    phase_id = util.check_string(data, "phase_budget_id")
    phase = db.phase_budgets.get(phase_id)
    if phase is None or phase.get("firm_id") != firmId:
        from errors import err_not_found
        raise err_not_found(f"PhaseBudget {phase_id} not found")
    delta = util.check_int(data, "delta_cents")
    reason = util.check_string(data, "scope_change_reason")

    supersedes_id = data.get("supersedes_amendment_id")
    if supersedes_id is not None:
        target = db.budget_amendments.get(supersedes_id)
        if target is None or target.get("firm_id") != firmId:
            from errors import err_not_found
            raise err_not_found(f"BudgetAmendment {supersedes_id} not found")

    amd = util.new_resource()
    amd.update({
        "matter_id": matter["id"],
        "firm_id": firmId,
        "phase_budget_id": phase["id"],
        "delta_cents": delta,
        "scope_change_reason": reason,
        "supersedes_amendment_id": supersedes_id,
        "requested_by_user_id": ctx.user_id,
        "decided_by_user_id": None,
        "status": "DRAFT",
    })

    # Creation-time guards (PRD §3.7): supersede validity, non-negative result.
    if supersedes_id is not None:
        target = db.budget_amendments.get(supersedes_id)
        if target.get("status") not in ("REJECTED", "SUPERSEDED"):
            raise ApiError(ERR_AMENDMENT_SUPERSEDE_INVALID,
                           "supersedes_amendment_id references amendment not in REJECTED/SUPERSEDED", 409)
    if int(phase.get("current_budget_cents", 0)) + delta < 0:
        raise ApiError(ERR_AMENDMENT_NEGATIVE_BUDGET,
                       "Amendment would drive current_budget_cents negative", 422)

    db.budget_amendments[amd["id"]] = amd
    return success_object(amd, 201)


@bp.get("/firms/budget_amendments/<amendmentId>")
def get_amendment(amendmentId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    amd = util.get_amendment_flat(amendmentId)
    return success_object(amd, 200)


@bp.get("/firms/budget_amendments")
def list_amendments():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters([
        "firm_id", "matter_id", "phase_budget_id", "supersedes_amendment_id", "status",
    ])
    items = util.apply_filters(list(db.budget_amendments.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/budget_amendments")
def list_amendments_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    filters = util.query_filters(["status", "phase_budget_id"])
    items = [a for a in db.budget_amendments.values() if a.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/phase_budgets/<phaseBudgetId>/budget_amendments")
def list_amendments_for_phase(phaseBudgetId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    phase = util.get_phase_flat(phaseBudgetId)
    items = [a for a in db.budget_amendments.values() if a.get("phase_budget_id") == phase["id"]]
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/budget_amendments/<amendmentId>/submit")
def submit_amendment(firmId, amendmentId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst")
    firm = util.get_firm(firmId)
    amd = util.get_amendment_scoped(firmId, amendmentId)
    if amd["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT amendment can be submitted", 409)

    phase = db.phase_budgets.get(amd.get("phase_budget_id"))
    if phase is None:
        from errors import err_not_found
        raise err_not_found("PhaseBudget not found")
    matter = db.matters.get(amd.get("matter_id"))
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")

    # Six-part battery in order (PRD §3.7).
    if phase.get("status") not in ("ACTIVE", "AMENDED"):
        raise ApiError(ERR_PHASE_NOT_AMENDABLE,
                       "Amendment target PhaseBudget not in ACTIVE/AMENDED", 409)
    if matter.get("status") not in ("ACTIVE", "REOPENED"):
        raise ApiError(ERR_MATTER_NOT_OPEN,
                       "Matter not in ACTIVE/REOPENED for amendment submission", 409)
    if amd.get("supersedes_amendment_id"):
        target = db.budget_amendments.get(amd["supersedes_amendment_id"])
        if target is None or target.get("status") not in ("REJECTED", "SUPERSEDED"):
            raise ApiError(ERR_AMENDMENT_SUPERSEDE_INVALID,
                           "supersedes_amendment_id references amendment not in REJECTED/SUPERSEDED", 409)
    if int(amd.get("delta_cents", 0)) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "delta_cents must not be zero", 400)
    if int(phase.get("current_budget_cents", 0)) + int(amd["delta_cents"]) < 0:
        raise ApiError(ERR_AMENDMENT_NEGATIVE_BUDGET,
                       "Amendment would drive current_budget_cents negative", 422)
    last_activity = matter.get("last_activity_period_index")
    if last_activity is not None and int(last_activity) <= int(firm.get("closed_through_period_index", -1)):
        raise ApiError(ERR_PERIOD_CLOSED,
                       "Matter cannot be retroactively amended into a closed period", 409)

    amd["status"] = "PENDING_REVIEW"
    util.touch(amd)
    return success_object(amd, 200)


@bp.post("/firms/<firmId>/budget_amendments/<amendmentId>/decide")
def decide_amendment(firmId, amendmentId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    util.get_firm(firmId)
    amd = util.get_amendment_scoped(firmId, amendmentId)
    if amd["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a PENDING_REVIEW amendment can be decided", 409)

    matter = db.matters.get(amd.get("matter_id"))
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")

    data = util.body()
    decision = data.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT", 400)

    # OCC on the parent matter (PRD §2.7) — checked before business gates.
    expected = data.get("expected_matter_version")
    if expected is not None:
        if not util.is_int(expected):
            raise ApiError(ERR_INVALID_REQUEST,
                           "expected_matter_version must be an integer", 400)
        if int(expected) != int(matter.get("version", 1)):
            raise ApiError(ERR_STALE_VERSION,
                           "OCC mismatch on expected_matter_version", 412)

    # Segregation of duties first, authority second (PRD §3.7).
    if ctx.user_id == amd.get("requested_by_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Same user cannot request and decide", 409)
    magnitude = abs(int(amd.get("delta_cents", 0)))
    if ctx.role == "BillingPartner" and magnitude > PARTNER_AMENDMENT_AUTHORITY_CENTS:
        raise ApiError(ERR_AMENDMENT_AUTHORITY_EXCEEDED,
                       "Amendment magnitude exceeds BillingPartner authority; requires ManagingPartner", 403)

    amd["decided_by_user_id"] = ctx.user_id

    if decision == "APPROVE":
        phase = db.phase_budgets.get(amd.get("phase_budget_id"))
        if phase is None:
            from errors import err_not_found
            raise err_not_found("PhaseBudget not found")
        phase["current_budget_cents"] = int(phase.get("current_budget_cents", 0)) + int(amd["delta_cents"])
        phase["version_in_force"] = int(phase.get("version_in_force", 1)) + 1
        phase["status"] = "AMENDED"
        util.touch(phase)

        if amd.get("supersedes_amendment_id"):
            target = db.budget_amendments.get(amd["supersedes_amendment_id"])
            if target is not None and target.get("status") in ("REJECTED", "SUPERSEDED"):
                target["status"] = "SUPERSEDED"
                util.touch(target)

        amd["status"] = "APPROVED"
        util.touch(amd)
        derived.recompute_matter(matter)
    else:
        amd["status"] = "REJECTED"
        util.touch(amd)
        util.touch(matter)

    return success_object(amd, 200)
