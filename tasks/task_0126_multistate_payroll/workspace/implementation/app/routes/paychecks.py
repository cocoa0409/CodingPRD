"""Paycheck routes — calculate, recalculate, approve, mark-paid, issue-correction."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from flask import Blueprint, request

from ..auth import (
    ROLE_PAYROLL_MANAGER,
    ROLE_PAYROLL_SPECIALIST,
    ROLE_TREASURER,
    require_roles,
)
from ..clock import now_iso, parse_iso_date_str
from ..errors import (
    err_negative_net_pay,
    err_no_w4,
    err_pay_period_not_found,
    err_pay_period_not_open,
    err_paycheck_not_approved,
    err_paycheck_not_calculated,
    err_paycheck_not_correctable,
    err_paycheck_not_draft,
    err_paycheck_not_found,
    err_segregation_of_duties,
    err_terminated_employee,
)
from ..helpers import (
    new_uuid,
    occ_check,
    paginate,
    parse_pagination,
    require_json_object,
    round_half_up,
)
from ..responses import listing, ok
from ..services.calculations import (
    compute_gross_cents,
    compute_non_retro_gross_cents,
    federal_withholding_annualized,
    federal_withholding_with_retro,
    garnishment_waterfall,
    local_withholding,
    medicare_additional,
    medicare_base,
    piecewise_tier_apply,
    social_security,
    state_withholding_annualized,
    state_withholding_with_retro,
)
from ..services.constants import (
    FED_BRACKETS,
    FINAL_SETTLEMENT_WINDOW_DAYS,
    PAY_PERIODS_PER_YEAR,
    STANDARD_DEDUCTION_CENTS,
)
from ..services.garnishments import (
    recompute_amount_collected,
    recompute_orders_affected_by_paycheck,
)
from ..services.ledger import (
    append_ledger_entry,
    recompute_employee_ytd,
)
from ..services.lookups import (
    active_garnishments_for_employee,
    find_active_w4_at_pay_date,
    paychecks_in_pay_period,
    previous_paycheck_for_employee,
)
from ..services.serialize import serialize_paycheck
from ..store import store

bp = Blueprint("paychecks", __name__)


def _get_paycheck_or_404(pc_id: str) -> dict:
    pc = store().paychecks.get(pc_id)
    if pc is None:
        raise err_paycheck_not_found()
    return pc


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

@bp.get("/paychecks")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_paychecks(**_kw):
    limit, offset = parse_pagination()
    pp_filter = request.args.get("pay_period_id")
    emp_filter = request.args.get("employee_id")
    status_filter = request.args.get("status")
    with store().lock:
        items = list(store().paychecks.values())
        if pp_filter:
            items = [p for p in items if p["pay_period_id"] == pp_filter]
        if emp_filter:
            items = [p for p in items if p["employee_id"] == emp_filter]
        if status_filter:
            items = [p for p in items if p["status"] == status_filter]
        items.sort(key=lambda p: (p["created_at"], p["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_paycheck(p) for p in page], total, limit, offset)


@bp.get("/paychecks/<pc_id>")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def get_paycheck(pc_id: str, **_kw):
    with store().lock:
        pc = _get_paycheck_or_404(pc_id)
        return ok(serialize_paycheck(pc))


# ---------------------------------------------------------------------------
# Helpers — calculate
# ---------------------------------------------------------------------------

def _ytd_reconciliation_federal_withholding(
    this_gross_cents: int,
    employee_ytd_gross_before: int,
    w4: dict[str, Any],
    periods_elapsed: int,
) -> int:
    """YTD true-up: cumulative expected fed tax minus what's already been withheld YTD."""
    filing_status = w4["filing_status"]
    std_full = STANDARD_DEDUCTION_CENTS[filing_status]
    # Prorated standard deduction
    prorated_std = round_half_up(
        Decimal(std_full) * Decimal(periods_elapsed + 1) / Decimal(PAY_PERIODS_PER_YEAR)
    )
    cumulative_taxable = max(0, (employee_ytd_gross_before + this_gross_cents) - prorated_std)
    cumulative_expected_fed = piecewise_tier_apply(
        cumulative_taxable, FED_BRACKETS[filing_status]
    )
    # Subtract previously-withheld federal from prior approvals (this tax year)
    ytd_fed_already = _ytd_federal_withheld(w4_employee_id := w4["employee_id"])
    reconciled = cumulative_expected_fed - ytd_fed_already
    return max(0, reconciled)


def _ytd_federal_withheld(employee_id: str) -> int:
    """Sum of federal_withholding_cents on APPROVED-or-PAID paychecks for the employee
    in the current tax-year context. Used by reconciliation variant.

    Implementation: sum federal_withholding_cents on paychecks tied to ledger ACCRUAL
    entries (i.e., paychecks that contributed to YTD).
    """
    s = store()
    total = 0
    # Collect paycheck ids that have ACCRUAL ledger entries
    accrual_paycheck_ids = set()
    for e in s.ytd_ledger.values():
        if e["employee_id"] == employee_id and e["entry_kind"] == "ACCRUAL":
            accrual_paycheck_ids.add(e["paycheck_id"])
    # Subtract reversed ones
    reversed_paycheck_ids = set()
    for e in s.ytd_ledger.values():
        if e["employee_id"] == employee_id and e["entry_kind"] == "REVERSAL":
            reversed_paycheck_ids.add(e["paycheck_id"])
    effective_ids = accrual_paycheck_ids - reversed_paycheck_ids
    for pc_id in effective_ids:
        pc = s.paychecks.get(pc_id)
        if pc and pc.get("federal_withholding_cents") is not None:
            total += pc["federal_withholding_cents"]
    return total


def _periods_elapsed_in_year(employee_id: str, tax_year: int) -> int:
    """Count APPROVED (currently-in-ledger) paychecks for the employee in tax_year."""
    s = store()
    accrual = set()
    for e in s.ytd_ledger.values():
        if e["employee_id"] == employee_id and e["tax_year"] == tax_year and e["entry_kind"] == "ACCRUAL":
            accrual.add(e["paycheck_id"])
    reversed_ids = set()
    for e in s.ytd_ledger.values():
        if e["employee_id"] == employee_id and e["tax_year"] == tax_year and e["entry_kind"] == "REVERSAL":
            reversed_ids.add(e["paycheck_id"])
    return len(accrual - reversed_ids)


def _should_use_ytd_reconciliation(paycheck: dict, employee: dict, tax_year: int) -> bool:
    """Reconciliation kicks in when:
       1. Employee.ytd_gross_wages_cents > 0
       2. The most recent prior paycheck for this employee was VOIDED in same tax_year.
    """
    if employee["ytd_gross_wages_cents"] <= 0:
        return False
    prev = previous_paycheck_for_employee(employee["id"], paycheck)
    if prev is None:
        return False
    if prev["status"] != "VOIDED":
        return False
    # Same tax_year was already enforced by previous_paycheck_for_employee
    return True


# ---------------------------------------------------------------------------
# Calculate
# ---------------------------------------------------------------------------

@bp.post("/paychecks/<pc_id>/calculate")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def calculate(pc_id: str, _caller_id: str | None = None, **_kw):
    s = store()
    with s.lock:
        pc = _get_paycheck_or_404(pc_id)
        body = require_json_object()
        version = body.get("version")
        pp = s.pay_periods[pc["pay_period_id"]]
        # priority 4: PayPeriod OPEN
        if pp["status"] != "OPEN":
            raise err_pay_period_not_open()
        # priority 5: Paycheck must be DRAFT
        if pc["status"] != "DRAFT":
            raise err_paycheck_not_draft()
        # OCC
        occ_check(version, pc["version"])

        # Business referential checks (after state)
        emp = s.employees[pc["employee_id"]]
        pay_date = parse_iso_date_str(pp["pay_date"])

        # ERR_TERMINATED_EMPLOYEE: must be ACTIVE OR within final-settlement window.
        # PRD §3.1: "the owning pay period's period_end is within seven days of
        # the recorded termination_date". Interpreted as absolute distance — the
        # period_end must lie no more than seven days from termination_date in
        # either direction. (A pe earlier than td-7 means the period predates
        # termination by too far to be a final-settlement remediation; a pe
        # later than td+7 means the run is too far after termination.)
        if emp["status"] == "TERMINATED":
            term_date_iso = emp.get("termination_date")
            allowed = False
            if term_date_iso:
                td = parse_iso_date_str(term_date_iso)
                pe = parse_iso_date_str(pp["period_end"])
                delta = abs((pe - td).days)
                if delta <= FINAL_SETTLEMENT_WINDOW_DAYS:
                    allowed = True
            if not allowed:
                raise err_terminated_employee()

        # ERR_NO_W4
        w4 = find_active_w4_at_pay_date(emp["id"], pay_date)
        if w4 is None:
            raise err_no_w4()

        # Snapshot the item
        item = s.payroll_items[pc["payroll_item_id"]]
        regular = float(item["regular_hours"])
        overtime = float(item["overtime_hours"])
        double = float(item["double_hours"])
        retro = int(item["retro_adjustment_cents"])
        rate = int(emp["hourly_rate_cents"])

        gross = compute_gross_cents(regular, overtime, double, retro, rate)
        non_retro_gross = compute_non_retro_gross_cents(regular, overtime, double, rate)

        tax_year = pay_date.year
        # YTD reconciliation check
        use_reconciliation = _should_use_ytd_reconciliation(pc, emp, tax_year)

        # Federal withholding
        if use_reconciliation:
            periods_elapsed = _periods_elapsed_in_year(emp["id"], tax_year)
            fed_wh = _ytd_reconciliation_federal_withholding(
                gross,
                emp["ytd_gross_wages_cents"],
                w4,
                periods_elapsed,
            )
        elif retro != 0:
            fed_wh = federal_withholding_with_retro(non_retro_gross, retro, w4)
        else:
            fed_wh = federal_withholding_annualized(gross, w4)

        # State withholding
        if retro != 0:
            state_wh = state_withholding_with_retro(non_retro_gross, retro, emp["work_state"], w4)
        else:
            state_wh = state_withholding_annualized(gross, emp["work_state"], w4)

        # Local
        local_wh = local_withholding(gross, emp["work_locality"])

        # Social Security — uses pre-paycheck YTD
        ss_wh, ss_taxable = social_security(gross, emp["ytd_social_security_wages_cents"])

        # Medicare base & additional — uses pre-paycheck YTD
        med_base = medicare_base(gross)
        med_add = medicare_additional(gross, emp["ytd_medicare_wages_cents"])

        # Disposable income for garnishment waterfall
        disposable = gross - fed_wh - state_wh - local_wh - ss_wh - med_base - med_add
        active_orders = active_garnishments_for_employee(emp["id"], pay_date)
        garn_total, allocations = garnishment_waterfall(disposable, active_orders)

        # Net pay
        net = gross - fed_wh - state_wh - local_wh - ss_wh - med_base - med_add - garn_total

        ts = now_iso()
        pc["gross_wages_cents"] = gross
        pc["federal_withholding_cents"] = fed_wh
        pc["state_withholding_cents"] = state_wh
        pc["local_withholding_cents"] = local_wh
        pc["social_security_cents"] = ss_wh
        pc["medicare_base_cents"] = med_base
        pc["medicare_additional_cents"] = med_add
        pc["garnishment_total_cents"] = garn_total
        pc["garnishment_allocations"] = allocations
        pc["net_pay_cents"] = net
        pc["status"] = "CALCULATED"
        pc["w4_profile_id"] = w4["id"]
        pc["calculator_id"] = _caller_id
        pc["ss_wages_subject_cents"] = ss_taxable
        pc["updated_at"] = ts
        pc["version"] = pc["version"] + 1

        # Lock the item
        item["locked"] = True
        item["updated_at"] = ts
        item["version"] = item["version"] + 1

        return ok(serialize_paycheck(pc))


# ---------------------------------------------------------------------------
# Recalculate (revert to DRAFT)
# ---------------------------------------------------------------------------

@bp.post("/paychecks/<pc_id>/recalculate")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def recalculate(pc_id: str, **_kw):
    s = store()
    with s.lock:
        pc = _get_paycheck_or_404(pc_id)
        body = require_json_object()
        version = body.get("version")
        pp = s.pay_periods[pc["pay_period_id"]]
        if pp["status"] != "OPEN":
            raise err_pay_period_not_open()
        if pc["status"] != "CALCULATED":
            raise err_paycheck_not_calculated()
        occ_check(version, pc["version"])
        ts = now_iso()
        for field in (
            "gross_wages_cents",
            "federal_withholding_cents",
            "state_withholding_cents",
            "local_withholding_cents",
            "social_security_cents",
            "medicare_base_cents",
            "medicare_additional_cents",
            "net_pay_cents",
        ):
            pc[field] = None
        pc["garnishment_total_cents"] = 0
        pc["garnishment_allocations"] = {}
        pc["w4_profile_id"] = None
        pc["calculator_id"] = None
        pc["ss_wages_subject_cents"] = 0
        pc["status"] = "DRAFT"
        pc["updated_at"] = ts
        pc["version"] = pc["version"] + 1
        # Unlock item
        item = s.payroll_items.get(pc["payroll_item_id"])
        if item:
            item["locked"] = False
            item["updated_at"] = ts
            item["version"] = item["version"] + 1
        return ok(serialize_paycheck(pc))


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

@bp.post("/paychecks/<pc_id>/approve")
@require_roles(ROLE_PAYROLL_MANAGER)
def approve(pc_id: str, _caller_id: str | None = None, **_kw):
    s = store()
    with s.lock:
        pc = _get_paycheck_or_404(pc_id)
        body = require_json_object()
        version = body.get("version")
        pp = s.pay_periods[pc["pay_period_id"]]
        # priority 4
        if pp["status"] != "OPEN":
            raise err_pay_period_not_open()
        # priority 5: must be CALCULATED
        if pc["status"] != "CALCULATED":
            raise err_paycheck_not_calculated()
        # priority 7: SOD — approver != calculator
        if pc.get("calculator_id") == _caller_id:
            raise err_segregation_of_duties("Approver must differ from calculator")
        # priority 15: ERR_NEGATIVE_NET_PAY
        if pc.get("net_pay_cents", 0) < 0:
            raise err_negative_net_pay()
        # priority 17: OCC
        occ_check(version, pc["version"])

        ts = now_iso()
        pc["status"] = "APPROVED"
        pc["approver_id"] = _caller_id
        pc["updated_at"] = ts
        pc["version"] = pc["version"] + 1

        # Side effects
        tax_year = parse_iso_date_str(pp["pay_date"]).year
        append_ledger_entry(
            employee_id=pc["employee_id"],
            paycheck_id=pc["id"],
            tax_year=tax_year,
            gross_delta_cents=pc["gross_wages_cents"],
            ss_wages_delta_cents=pc["ss_wages_subject_cents"],
            medicare_wages_delta_cents=pc["gross_wages_cents"],
            entry_kind="ACCRUAL",
        )
        recompute_employee_ytd(pc["employee_id"], tax_year)
        # Refresh affected garnishment orders
        recompute_orders_affected_by_paycheck(pc["id"])

        return ok(serialize_paycheck(pc))


# ---------------------------------------------------------------------------
# Mark paid
# ---------------------------------------------------------------------------

@bp.post("/paychecks/<pc_id>/mark-paid")
@require_roles(ROLE_TREASURER)
def mark_paid(pc_id: str, _caller_id: str | None = None, **_kw):
    s = store()
    with s.lock:
        pc = _get_paycheck_or_404(pc_id)
        body = require_json_object()
        version = body.get("version")
        if pc["status"] != "APPROVED":
            raise err_paycheck_not_approved()
        # SOD: Treasurer != approver and != calculator
        if _caller_id == pc.get("approver_id") or _caller_id == pc.get("calculator_id"):
            raise err_segregation_of_duties("Treasurer must differ from approver and calculator")
        occ_check(version, pc["version"])

        ts = now_iso()
        pc["status"] = "PAID"
        pc["updated_at"] = ts
        pc["version"] = pc["version"] + 1

        # Auto-close pay period if every paycheck is PAID or VOIDED and pp was LOCKED
        pp = s.pay_periods[pc["pay_period_id"]]
        all_paychecks = paychecks_in_pay_period(pp["id"])
        if pp["status"] == "LOCKED" and all(
            p["status"] in ("PAID", "VOIDED") for p in all_paychecks
        ):
            pp["status"] = "CLOSED"
            pp["updated_at"] = ts
            pp["version"] = pp["version"] + 1

        return ok(serialize_paycheck(pc))


# ---------------------------------------------------------------------------
# Issue correction
# ---------------------------------------------------------------------------

@bp.post("/paychecks/<pc_id>/issue-correction")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def issue_correction(pc_id: str, **_kw):
    s = store()
    with s.lock:
        pc = _get_paycheck_or_404(pc_id)
        body = require_json_object()
        version = body.get("version")
        target_pp_id = body.get("target_pay_period_id")
        if not isinstance(target_pp_id, str) or not target_pp_id.strip():
            from ..errors import err_invalid_request
            raise err_invalid_request("target_pay_period_id is required")
        # priority 5: source must be APPROVED or PAID
        if pc["status"] not in ("APPROVED", "PAID"):
            raise err_paycheck_not_correctable()
        occ_check(version, pc["version"])

        # If source is PAID, check the owning RemittancePeriod status
        # PAID→VOIDED: owning RemittancePeriod must be DRAFT or FINALIZED (not REMITTED)
        if pc["status"] == "PAID":
            src_pp = s.pay_periods[pc["pay_period_id"]]
            src_date = parse_iso_date_str(src_pp["pay_date"])
            for r in s.remittances.values():
                if r["tax_year"] == src_date.year and r["tax_month"] == src_date.month:
                    if r["status"] == "REMITTED":
                        # Per scaffold: "REMITTED triggers AMENDED path instead — different
                        # transition, same trigger" — the PRD says correction is still
                        # permitted but remittance enters amendment cycle separately.
                        # We still allow the void; the remittance is amended via separate
                        # /amend call. So no error here.
                        pass

        target_pp = s.pay_periods.get(target_pp_id)
        if target_pp is None:
            raise err_pay_period_not_found("target_pay_period_id not found")

        # Void the source — snapshot the prior allocations so we can
        # tell each affected order to recompute, then clear them. PRD
        # §3.5: void "subtracts" the per-order allocation, and the
        # derivation rule (sum APPROVED|PAID minus sum VOIDED) must
        # match the stored figure. Clearing the VOIDED paycheck's
        # allocations is the only representation that lets a later
        # re-approved correction with identical inputs restore the
        # original total — the conservation invariant pinned by PRD.
        prior_allocations = dict(pc.get("garnishment_allocations") or {})
        ts = now_iso()
        pc["status"] = "VOIDED"
        pc["garnishment_allocations"] = {}
        pc["garnishment_total_cents"] = 0
        pc["updated_at"] = ts
        pc["version"] = pc["version"] + 1

        # Append REVERSAL ledger entry (negated deltas of source)
        src_pp = s.pay_periods[pc["pay_period_id"]]
        tax_year = parse_iso_date_str(src_pp["pay_date"]).year
        append_ledger_entry(
            employee_id=pc["employee_id"],
            paycheck_id=pc["id"],
            tax_year=tax_year,
            gross_delta_cents=-pc["gross_wages_cents"],
            ss_wages_delta_cents=-pc["ss_wages_subject_cents"],
            medicare_wages_delta_cents=-pc["gross_wages_cents"],
            entry_kind="REVERSAL",
        )
        recompute_employee_ytd(pc["employee_id"], tax_year)

        # Recompute garnishments for orders that were allocated against
        # the source (we cleared them above, so explicitly walk the
        # prior set).
        for order_id in prior_allocations:
            recompute_amount_collected(order_id)

        # Create new DRAFT correction paycheck attached to target_pay_period_id
        new_pc_id = new_uuid()
        new_pc = {
            "id": new_pc_id,
            "pay_period_id": target_pp_id,
            "payroll_item_id": pc["payroll_item_id"],
            "employee_id": pc["employee_id"],
            "w4_profile_id": None,
            "gross_wages_cents": None,
            "federal_withholding_cents": None,
            "state_withholding_cents": None,
            "local_withholding_cents": None,
            "social_security_cents": None,
            "medicare_base_cents": None,
            "medicare_additional_cents": None,
            "garnishment_total_cents": 0,
            "garnishment_allocations": {},
            "net_pay_cents": None,
            "is_retro_correction": True,
            "correction_of_paycheck_id": pc["id"],
            "status": "DRAFT",
            "calculator_id": None,
            "approver_id": None,
            "ss_wages_subject_cents": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.paychecks[new_pc_id] = new_pc
        # Target pay period gains a paycheck
        target_pp["paycheck_count"] = target_pp["paycheck_count"] + 1
        target_pp["updated_at"] = ts
        target_pp["version"] = target_pp["version"] + 1

        # Return the NEW correction paycheck (the more useful response)
        return ok(serialize_paycheck(new_pc))
