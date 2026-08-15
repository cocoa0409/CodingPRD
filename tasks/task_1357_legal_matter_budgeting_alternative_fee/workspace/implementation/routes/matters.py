"""Matter endpoints: CRUD, lifecycle, quote, variance (PRD §3.2, §3.5, §3.9)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_HAS_OPEN_WIP,
    ERR_MATTER_HAS_PENDING_WRITE_DOWNS,
    ERR_MATTER_HAS_PENDING_AMENDMENTS,
    ERR_MATTER_COLLAR_UNSETTLED,
    ERR_MATTER_ACCRUAL_OUTSTANDING,
    ERR_REOPEN_WINDOW_CLOSED,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("matters", __name__)

LITIGATION_STAGES = {"INTAKE", "PLEADINGS", "DISCOVERY", "PRETRIAL", "TRIAL", "APPEAL"}
ARRANGEMENT_TYPES = {"FLAT_FEE", "CAPPED_FEE", "SUCCESS_FEE", "COLLAR"}

READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner",
              "ManagingPartner", "Timekeeper", "ClientContact")
LIST_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner",
              "ManagingPartner", "ClientContact")


@bp.post("/firms/<firmId>/clients/<clientId>/matters")
def create_matter(firmId, clientId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "BillingPartner")
    client = util.get_client_scoped(firmId, clientId)
    data = util.body()
    util.require_fields(data, ["matter_number", "title", "litigation_stage", "responsible_partner_id"])
    matter_number = util.check_string(data, "matter_number")
    title = util.check_string(data, "title")
    stage = util.check_enum(data, "litigation_stage", LITIGATION_STAGES)
    partner_id = util.check_string(data, "responsible_partner_id")
    partner = db.timekeepers.get(partner_id)
    if partner is None or partner.get("firm_id") != firmId:
        from errors import err_not_found
        raise err_not_found(f"Timekeeper {partner_id} not found")

    matter = util.new_resource()
    matter.update({
        "client_id": client["id"],
        "firm_id": firmId,
        "matter_number": matter_number,
        "title": title,
        "litigation_stage": stage,
        "responsible_partner_id": partner_id,
        "status": "OPEN",
        "fee_arrangement_id": None,
        "budget_total_cents": 0,
        "actual_fees_cents": 0,
        "write_down_total_cents": 0,
        "variance_cents": 0,
        "variance_pct_bp": None,
        "variance_alert_level": "NONE",
        "revised_forecast_cents": 0,
        "realization_rate_bp": 10000,
        "last_activity_period_index": None,
        "closed_period_index": None,
    })
    db.matters[matter["id"]] = matter
    return success_object(matter, 201)


@bp.get("/firms/matters/<matterId>")
def get_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    derived.recompute_phase_actuals(matterId)
    derived.recompute_matter(matter, bump=False)
    return success_object(matter, 200)


@bp.get("/firms/matters")
def list_matters():
    ctx = get_context()
    require_roles(ctx, *LIST_ROLES)
    filters = util.query_filters([
        "firm_id", "client_id", "responsible_partner_id",
        "fee_arrangement_id", "status", "litigation_stage",
    ])
    items = util.apply_filters(list(db.matters.values()), filters)
    for m in items:
        derived.recompute_phase_actuals(m["id"])
        derived.recompute_matter(m, bump=False)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/clients/<clientId>/matters")
def list_matters_for_client(clientId):
    ctx = get_context()
    require_roles(ctx, *LIST_ROLES)
    client = util.get_client_flat(clientId)
    filters = util.query_filters(["status", "litigation_stage"])
    items = [m for m in db.matters.values() if m.get("client_id") == client["id"]]
    items = util.apply_filters(items, filters)
    for m in items:
        derived.recompute_phase_actuals(m["id"])
        derived.recompute_matter(m, bump=False)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/matters/<matterId>/suspend")
def suspend_matter(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    matter = util.get_matter_scoped(firmId, matterId)
    if matter["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only an ACTIVE matter can be suspended", 409)
    matter["status"] = "SUSPENDED"
    util.touch(matter)
    return success_object(matter, 200)


@bp.post("/firms/<firmId>/matters/<matterId>/resume")
def resume_matter(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    matter = util.get_matter_scoped(firmId, matterId)
    if matter["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a SUSPENDED matter can be resumed", 409)
    matter["status"] = "ACTIVE"
    util.touch(matter)
    return success_object(matter, 200)


@bp.post("/firms/<firmId>/matters/<matterId>/close")
def close_matter(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    firm = util.get_firm(firmId)
    matter = util.get_matter_scoped(firmId, matterId)
    if matter["status"] not in ("ACTIVE", "SUSPENDED", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Matter cannot be closed from its current state", 409)

    # Five-part close battery, evaluated in order (PRD §3.9).
    open_wip = [
        e for e in derived.entries_of(matterId)
        if e.get("status") in ("DRAFT", "SUBMITTED", "APPROVED")
    ]
    if open_wip:
        raise ApiError(ERR_MATTER_HAS_OPEN_WIP,
                       "Cannot close matter with DRAFT/SUBMITTED/APPROVED time entries", 409)

    pending_wd = [
        w for w in derived.write_downs_of(matterId)
        if w.get("status") in ("DRAFT", "PENDING_PARTNER", "PENDING_MANAGING_PARTNER")
    ]
    if pending_wd:
        raise ApiError(ERR_MATTER_HAS_PENDING_WRITE_DOWNS,
                       "Cannot close matter with non-terminal WriteDownRequest", 409)

    pending_amd = [
        a for a in derived.amendments_of(matterId)
        if a.get("status") in ("DRAFT", "PENDING_REVIEW")
    ]
    if pending_amd:
        raise ApiError(ERR_MATTER_HAS_PENDING_AMENDMENTS,
                       "Cannot close matter with DRAFT/PENDING_REVIEW BudgetAmendment", 409)

    arrangement = None
    if matter.get("fee_arrangement_id"):
        arrangement = db.fee_arrangements.get(matter["fee_arrangement_id"])
    if arrangement is None:
        for a in derived.arrangements_of(matterId):
            if a.get("status") == "ACTIVE":
                arrangement = a
                break
    if arrangement is not None and arrangement.get("arrangement_type") == "COLLAR":
        year_ended = util.fiscal_year_ended(firm, int(arrangement.get("fiscal_year_index", 0)))
        if not year_ended:
            # A true-up record in flight also signals the year has ended.
            year_ended = any(
                t.get("fee_arrangement_id") == arrangement["id"]
                for t in derived.true_ups_of(matterId)
            )
        if year_ended:
            true_ups = [
                t for t in derived.true_ups_of(matterId)
                if t.get("fee_arrangement_id") == arrangement["id"]
            ]
            settled = any(t.get("status") in ("SETTLED", "WAIVED") for t in true_ups)
            if not settled:
                raise ApiError(ERR_MATTER_COLLAR_UNSETTLED,
                               "Cannot close COLLAR matter with unsettled year-end true-up", 409)

    client = db.clients.get(matter.get("client_id"))
    if client is not None and client.get("accrual_reporting_required"):
        reports = derived.reports_of(matterId)
        if reports:
            latest = max(reports, key=lambda r: (r.get("period_index", 0), util.order_key(r)))
            if latest.get("status") not in ("SUBMITTED", "ACKNOWLEDGED"):
                raise ApiError(ERR_MATTER_ACCRUAL_OUTSTANDING,
                               "Latest accrual report is not SUBMITTED or ACKNOWLEDGED", 409)
        else:
            raise ApiError(ERR_MATTER_ACCRUAL_OUTSTANDING,
                           "Client requires accrual reporting but no report exists", 409)

    matter["status"] = "CLOSED"
    matter["closed_period_index"] = int(firm.get("closed_through_period_index", -1)) + 1
    util.touch(matter)
    return success_object(matter, 200)


@bp.post("/firms/<firmId>/matters/<matterId>/reopen")
def reopen_matter(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "ManagingPartner")
    firm = util.get_firm(firmId)
    matter = util.get_matter_scoped(firmId, matterId)
    if matter["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a CLOSED matter can be reopened", 409)
    # Reopen window (PRD §3.9): a matter closed in a period at or before
    # closed_through_period_index has aged past the books; such a closure may
    # be reopened only within closed_through_period_index + 2 periods of the
    # closure. The boundary is pinned inclusive: exactly two periods of age
    # still reopens.
    closed_period = matter.get("closed_period_index")
    if closed_period is None:
        closed_period = int(firm.get("current_period_index", 0))
    ct = int(firm.get("closed_through_period_index", -1))
    if int(closed_period) <= ct and (ct - int(closed_period)) >= 2:
        raise ApiError(ERR_REOPEN_WINDOW_CLOSED,
                       "Reopen attempted outside allowed window", 409)
    matter["status"] = "REOPENED"
    matter["closed_period_index"] = None
    util.touch(matter)
    return success_object(matter, 200)


@bp.get("/firms/<firmId>/matters/<matterId>/quote")
def quote_matter(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst", "BillingPartner", "ManagingPartner")
    matter = util.get_matter_scoped(firmId, matterId)
    arrangement_type = util.check_enum(
        {"arrangement_type": _query_param("arrangement_type")},
        "arrangement_type", ARRANGEMENT_TYPES,
    )

    # Type-specific figures come from the matter's current ACTIVE (or latest
    # PENDING_APPROVAL) arrangement — the candidate terms being priced.
    arrangement = None
    candidates = derived.arrangements_of(matterId)
    for a in candidates:
        if a.get("status") == "ACTIVE":
            arrangement = a
            break
    if arrangement is None:
        pending = [a for a in candidates if a.get("status") == "PENDING_APPROVAL"]
        if pending:
            arrangement = max(pending, key=util.order_key)

    phases = [
        p for p in derived.phases_of(matterId)
        if p.get("status") in ("ACTIVE", "AMENDED")
    ]
    phases.sort(key=util.order_key)

    phase_quotes = []
    for p in phases:
        base = int(p.get("current_budget_cents", 0))
        if arrangement_type == "CAPPED_FEE":
            cap = (arrangement or {}).get("capped_fee_cents")
            quote = min(base, int(cap)) if cap is not None else base
        else:
            # FLAT_FEE / SUCCESS_FEE / COLLAR keep the per-phase figure at the
            # phase's current budget.
            quote = base
        quote = int(Decimal(quote).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        phase_quotes.append({
            "phase_budget_id": p["id"],
            "task_code": p.get("task_code"),
            "litigation_stage": p.get("litigation_stage"),
            "quote_cents": quote,
        })

    phase_sum = sum(pq["quote_cents"] for pq in phase_quotes)
    if arrangement_type == "FLAT_FEE":
        flat = (arrangement or {}).get("flat_fee_cents")
        total = int(flat) if flat is not None else phase_sum
    elif arrangement_type == "SUCCESS_FEE":
        uplift = (arrangement or {}).get("success_fee_uplift_pct_bp") or 0
        total_val = Decimal(phase_sum) * (Decimal(10000) + Decimal(int(uplift))) / Decimal(10000)
        total = int(total_val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # CAPPED_FEE or COLLAR: sum of rounded phase quotes
        total = phase_sum

    return success_object({"total_quote_cents": total, "phase_quotes": phase_quotes}, 200)


@bp.get("/firms/<firmId>/matters/<matterId>/variance")
def variance_matter(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst", "BillingPartner", "ManagingPartner")
    matter = util.get_matter_scoped(firmId, matterId)
    derived.recompute_phase_actuals(matterId)
    derived.recompute_matter(matter, bump=False)
    data = {
        "variance_cents": matter.get("variance_cents"),
        "variance_pct_bp": matter.get("variance_pct_bp"),
        "variance_alert_level": matter.get("variance_alert_level"),
        "revised_forecast_cents": matter.get("revised_forecast_cents"),
        "realization_rate_bp": matter.get("realization_rate_bp"),
    }
    return success_object(data, 200)


def _query_param(name):
    from flask import request
    return request.args.get(name)
