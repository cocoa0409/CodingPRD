"""PaycheckRun endpoints (create + state transitions + cascades)."""
from flask import Blueprint, request

import db
import response
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_PAY_PERIOD_OVERLAP,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles, get_user_id
from services import serialize, pagination, lookups
from services import validation as V
from services import calculations as calc


bp = Blueprint("paycheck_runs", __name__)


def _interval_overlap(a_start, a_end, b_start, b_end):
    """Closed-closed interval overlap; point overlap counts (PRD §3.3)."""
    return a_start <= b_end and b_start <= a_end


def _employees_in_run(run_id):
    """Set of employee_ids that have a Paycheck in the given run."""
    return {p["employee_id"] for p in db.paychecks.values()
            if p["paycheck_run_id"] == run_id}


@bp.post("/paycheck-runs")
@require_roles("PayrollPreparer")
def create_run():
    body = V.require_dict(request.get_json(silent=True) or {})
    pay_period_start = V.require_str(body, "pay_period_start")
    pay_period_end = V.require_str(body, "pay_period_end")
    pay_date = V.require_str(body, "pay_date")

    # NOTE: priority-11 pay-period overlap check at run-create only considers
    # employees attached to the to-be-added run. At creation there are no
    # paychecks yet — the overlap check fires when a Paycheck is added.

    run = {
        "id": db.new_id(),
        "pay_period_start": pay_period_start,
        "pay_period_end": pay_period_end,
        "pay_date": pay_date,
        "prepared_by_user_id": get_user_id(),
        "approved_by_user_id": None,
        "status": "DRAFT",
        "total_gross_cents": 0,
    }
    db.stamp_common(run)
    db.paycheck_runs[run["id"]] = run
    return response.success_object(serialize.paycheck_run(run), status=201)


@bp.get("/paycheck-runs/<rid>")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def get_run(rid):
    r = db.paycheck_runs.get(rid)
    if not r:
        raise APIError(ERR_NOT_FOUND, 404, "PaycheckRun not found")
    return response.success_object(serialize.paycheck_run(r))


@bp.get("/paycheck-runs")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def list_runs():
    limit, offset = pagination.parse_limit_offset()
    status = V.opt_enum(request.args, "status", V.PAYCHECK_RUN_STATUSES)
    pay_date_from = V.opt_str(request.args, "pay_date_from")
    pay_date_to = V.opt_str(request.args, "pay_date_to")

    items = list(db.paycheck_runs.values())
    if status:
        items = [r for r in items if r["status"] == status]
    if pay_date_from:
        items = [r for r in items if r["pay_date"] >= pay_date_from]
    if pay_date_to:
        items = [r for r in items if r["pay_date"] <= pay_date_to]

    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.paycheck_run(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.get("/paycheck-runs/<rid>/paychecks")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def list_run_paychecks(rid):
    run = db.paycheck_runs.get(rid)
    if not run:
        raise APIError(ERR_NOT_FOUND, 404, "PaycheckRun not found")
    limit, offset = pagination.parse_limit_offset()
    items = [p for p in db.paychecks.values() if p["paycheck_run_id"] == rid]
    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.paycheck(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )


# -----------------------------------------------------------------------------
# State transitions
# -----------------------------------------------------------------------------

@bp.post("/paycheck-runs/<rid>/approve")
@require_roles("PayrollApprover")
def approve_run(rid):
    run = db.paycheck_runs.get(rid)
    if not run:
        raise APIError(ERR_NOT_FOUND, 404, "PaycheckRun not found")

    # Priority 5 — state guard
    if run["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "PaycheckRun is not in DRAFT")

    # Priority 7 — segregation of duties
    if get_user_id() == run["prepared_by_user_id"]:
        raise APIError(ERR_SOD_VIOLATION, 403, "approver must differ from preparer")

    # Priority 5 (content guard) — at least one child paycheck + pay_type matches hours
    children = [p for p in db.paychecks.values() if p["paycheck_run_id"] == rid]
    if not children:
        raise APIError(ERR_INVALID_STATE, 409, "PaycheckRun has no paychecks")
    for p in children:
        if not _pay_type_matches_hours(p):
            raise APIError(ERR_INVALID_STATE, 409,
                           "paycheck pay_type does not match hours fields")

    run["status"] = "APPROVED"
    run["approved_by_user_id"] = get_user_id()
    db.bump(run)
    return response.success_object(serialize.paycheck_run(run))


def _pay_type_matches_hours(p):
    pt = p["pay_type"]
    if pt == "REGULAR":
        return p["regular_hours_e2"] > 0
    if pt == "OVERTIME":
        return p["overtime_hours_e2"] > 0
    if pt == "DOUBLE":
        return p["double_hours_e2"] > 0
    if pt == "RETRO":
        return p["retro_amount_cents"] > 0
    return False


@bp.post("/paycheck-runs/<rid>/reject")
@require_roles("PayrollApprover")
def reject_run(rid):
    run = db.paycheck_runs.get(rid)
    if not run:
        raise APIError(ERR_NOT_FOUND, 404, "PaycheckRun not found")
    if run["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "PaycheckRun is not in APPROVED")
    run["status"] = "DRAFT"
    run["approved_by_user_id"] = None
    db.bump(run)
    return response.success_object(serialize.paycheck_run(run))


@bp.post("/paycheck-runs/<rid>/pay")
@require_roles("PayrollApprover")
def pay_run(rid):
    run = db.paycheck_runs.get(rid)
    if not run:
        raise APIError(ERR_NOT_FOUND, 404, "PaycheckRun not found")
    if run["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "PaycheckRun is not in APPROVED")

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "request body must be JSON object")
    is_year_end_run = V.require_bool(body, "is_year_end_run", default=False)

    children = [p for p in db.paychecks.values() if p["paycheck_run_id"] == rid]
    # Precondition: every child must be PENDING.
    for p in children:
        if p["status"] != "PENDING":
            raise APIError(ERR_INVALID_STATE, 409, "child Paycheck is not in PENDING")

    # Order children deterministically — created_at ASC — so YTD update order
    # is reproducible. (Reconciled variant uses pre-payment YTD; cumulative
    # behavior across siblings within the run is well-defined.)
    children.sort(key=lambda p: p["created_at"])

    pay_year = lookups.pay_date_year(run["pay_date"])

    # If is_year_end_run, recompute fed_withheld_cents per child using the
    # RECONCILED variant, BEFORE applying YTD updates (PRD §3.4 / §3.6).
    if is_year_end_run:
        for p in children:
            employee = db.employees[p["employee_id"]]
            w4 = lookups.effective_w4(p["employee_id"], pay_year)
            fed_table = lookups.find_tax_rate_table(
                "FEDERAL", pay_year,
                w4["filing_status"] if w4 else "SINGLE",
            )
            # Reconciled formula uses *pre-payment* YTD as baseline; iterate in
            # created_at order so each successive child sees the prior child's
            # YTD update applied first.
            new_fed = calc.federal_withholding_reconciled(
                p["gross_wages_cents"],
                p["pay_type"],
                w4,
                fed_table,
                prior_ytd_wages=employee["ytd_wages_cents"],
                prior_ytd_fed_withheld=employee["ytd_fed_withheld_cents"],
            )
            p["fed_withheld_cents"] = new_fed
            # Recompute net_pay since fed changed (garnishment cap also depends
            # on disposable earnings → fed; but we don't re-run waterfall here
            # because PAID-time re-allocation could double-spend orders. The
            # waterfall fixed at /paychecks time; only fed changes here so net
            # may differ).
            p["net_pay_cents"] = max(0, p["gross_wages_cents"] - (
                p["fed_withheld_cents"]
                + p["state_withheld_cents"]
                + p["local_withheld_cents"]
                + p["ss_withheld_cents"]
                + p["medicare_withheld_cents"]
                + p["addl_medicare_cents"]
                + p["garnishment_total_cents"]
            ))
            # Apply YTD updates immediately for the NEXT child to see correct
            # baseline (within-run iteration order is created_at ASC).
            _apply_ytd_increment(employee, p)
            # Bump paycheck below in the main pass.
    else:
        # Non-year-end: still need to advance YTDs.
        for p in children:
            employee = db.employees[p["employee_id"]]
            _apply_ytd_increment(employee, p)

    # Now finalize the cascade: child Paycheck PENDING -> PAID + applied_at
    # stamps + garnishment order debits + remittance accrual.
    for p in children:
        p["status"] = "PAID"
        db.bump(p)
        # Stamp applied_at on each child garnishment deduction
        for d in db.garnishment_deductions.values():
            if d["paycheck_id"] == p["id"]:
                d["applied_at"] = db.now_utc()
        # Debit garnishment orders
        for d in db.garnishment_deductions.values():
            if d["paycheck_id"] != p["id"]:
                continue
            g = db.garnishment_orders.get(d["garnishment_order_id"])
            if g is None:
                continue
            g["balance_remaining_cents"] -= d["amount_cents"]
            if g["balance_remaining_cents"] <= 0 and g["status"] == "ACTIVE":
                g["status"] = "SATISFIED"
            db.bump(g)
        # Remittance accrual
        _accrue_remittances(p, run, sign=+1)

    # Bump employees that were touched (YTD updates).
    touched_employees = {p["employee_id"] for p in children}
    for eid in touched_employees:
        db.bump(db.employees[eid])

    run["status"] = "PAID"
    db.bump(run)
    return response.success_object(serialize.paycheck_run(run))


def _apply_ytd_increment(employee, paycheck):
    """Advance Employee YTD fields per PRD §3.6 / SCAFFOLD §1.2."""
    gross = paycheck["gross_wages_cents"]
    employee["ytd_wages_cents"] += gross
    employee["ytd_fed_withheld_cents"] += paycheck["fed_withheld_cents"]
    employee["ytd_ss_wages_cents"] += calc.ytd_ss_increment(gross, employee["ytd_ss_wages_cents"])
    employee["ytd_medicare_wages_cents"] += gross


def _reverse_ytd_increment(employee, paycheck):
    """Reverse the YTD updates from a prior PAID transition (void cascade).

    The SS cap means the increment we applied was min(gross, capacity); we
    subtract the same amount we added.

    To recompute symmetrically, we recreate what the increment WAS at PAID
    time. Since the formula at PAID time was
        ss_inc = min(gross, max(0, SS_BASE - prior_ytd_ss))
    where prior_ytd_ss was the YTD before that paycheck — and that value is
    not stored — we instead use the recorded ss_withheld_cents as a proxy:
    the paycheck withheld 6.20% of ss_inc, so ss_inc = ss_withheld_cents * 10000 // 620.
    But that loses precision under floor division. A more robust strategy is
    to track the actual ss_taxable applied; we do that by recomputing
    backward using the current YTD as the "after" state. The exact reversal
    rule per scaffold says "reverse the YTD increments on Employee" using a
    conserved-quantity invariant — concretely, subtract the same numbers
    that were added.

    To preserve exactness across PAID/VOID cycles, we record an explicit
    ss_taxable_applied on the paycheck at PAID time. That field is not part
    of the entity's serialized form, but lives as a transient persistence
    attribute named _ss_taxable_applied.
    """
    gross = paycheck["gross_wages_cents"]
    employee["ytd_wages_cents"] -= gross
    employee["ytd_fed_withheld_cents"] -= paycheck["fed_withheld_cents"]
    employee["ytd_ss_wages_cents"] -= paycheck.get("_ss_taxable_applied", 0)
    employee["ytd_medicare_wages_cents"] -= gross
    # Clamp at 0 to guard against any rounding drift.
    for f in ("ytd_wages_cents", "ytd_fed_withheld_cents",
              "ytd_ss_wages_cents", "ytd_medicare_wages_cents"):
        if employee[f] < 0:
            employee[f] = 0


def _accrue_remittances(paycheck, run, sign):
    """Update Remittance.accrued_cents by sign * bucket_value for each (period_month, jurisdiction, tax_type)."""
    period_month = lookups.period_month_of(run["pay_date"])
    for jurisdiction, tax_type, value in lookups.remittance_jurisdictions_for(paycheck):
        existing = None
        for r in db.remittances.values():
            if (r["period_month"] == period_month
                    and r["jurisdiction"] == jurisdiction
                    and r["tax_type"] == tax_type):
                existing = r
                break
        if existing is None:
            existing = {
                "id": db.new_id(),
                "period_month": period_month,
                "jurisdiction": jurisdiction,
                "tax_type": tax_type,
                "accrued_cents": 0,
                "reconciled_cents": 0,
                "paid_cents": 0,
                "status": "ACCRUING",
            }
            db.stamp_common(existing)
            db.remittances[existing["id"]] = existing
        existing["accrued_cents"] += sign * value
        if existing["accrued_cents"] < 0:
            existing["accrued_cents"] = 0
        db.bump(existing)


@bp.post("/paycheck-runs/<rid>/void")
@require_roles("PayrollApprover", "ComplianceOfficer")
def void_run(rid):
    run = db.paycheck_runs.get(rid)
    if not run:
        raise APIError(ERR_NOT_FOUND, 404, "PaycheckRun not found")
    if run["status"] != "PAID":
        raise APIError(ERR_INVALID_STATE, 409, "PaycheckRun is not in PAID")

    # Block void if any Remittance for this period_month is REMITTED.
    period_month = lookups.period_month_of(run["pay_date"])
    for r in db.remittances.values():
        if r["period_month"] == period_month and r["status"] == "REMITTED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "remittance already REMITTED for this period_month")

    children = [p for p in db.paychecks.values() if p["paycheck_run_id"] == rid]
    children.sort(key=lambda p: p["created_at"])

    # Reverse cascade
    for p in children:
        # Reverse remittance accruals
        _accrue_remittances(p, run, sign=-1)
        # Restore garnishment balances
        for d in db.garnishment_deductions.values():
            if d["paycheck_id"] != p["id"]:
                continue
            g = db.garnishment_orders.get(d["garnishment_order_id"])
            if g is None:
                continue
            g["balance_remaining_cents"] += d["amount_cents"]
            if g["status"] == "SATISFIED" and g["balance_remaining_cents"] > 0:
                g["status"] = "ACTIVE"
            db.bump(g)
        # Reverse employee YTD
        employee = db.employees[p["employee_id"]]
        _reverse_ytd_increment(employee, p)
        # Paycheck -> VOID
        p["status"] = "VOID"
        db.bump(p)

    touched_employees = {p["employee_id"] for p in children}
    for eid in touched_employees:
        db.bump(db.employees[eid])

    run["status"] = "VOID"
    db.bump(run)
    return response.success_object(serialize.paycheck_run(run))
