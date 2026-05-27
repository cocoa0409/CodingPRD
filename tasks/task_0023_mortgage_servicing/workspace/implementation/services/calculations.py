"""Calculation rules per SCAFFOLD §1.3 / PRD §3."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from typing import Any

import db


# ---------- Constants ----------
GRACE_DAYS = 15
FORECLOSURE_THRESHOLD_DAYS = 120
SALE_NOTICE_DAYS = 30
MEDIATION_NOTICE_DAYS = 14
MAX_FORBEARANCE_DAYS = 360  # = MAX_FORBEARANCE_MONTHS (12) * 30
MAX_CUSHION_MONTHS = 2
LTV_BORROWER_REQUEST_BPS = 8000
LTV_AUTO_TERMINATION_BPS = 7800
LATE_FEE_PCT_BPS = 500
CLEAN_HISTORY_WINDOW_DAYS = 365
CLEAN_HISTORY_MAX_DPD = 30
FORECLOSURE_FEE_FLAT_CENTS = 250000
MONTHLY_DAYS = 30


# ---------- Helpers ----------
def round_half_up(value: Decimal) -> int:
    """Round a Decimal value to an integer using ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_to_cent(value: Decimal) -> int:
    """Ceil a Decimal value to the next integer cent."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))


# ---------- Amortization schedule ----------
def amortization_schedule(principal_cents: int, interest_rate_bps: int, term_months: int) -> int:
    """Compute scheduled monthly principal + interest in integer cents (round_half_up final)."""
    P = Decimal(principal_cents)
    n = term_months
    # r = interest_rate_bps / 10_000 / 12   (monthly fraction)
    r = Decimal(interest_rate_bps) / Decimal(10_000) / Decimal(12)
    if r == 0:
        return round_half_up(P / Decimal(n))
    # Use high precision intermediate (1+r)^n via Python power, then final round once.
    one_plus_r_to_n = (Decimal(1) + r) ** n
    monthly = P * r * one_plus_r_to_n / (one_plus_r_to_n - Decimal(1))
    return round_half_up(monthly)


# ---------- Payment posting waterfall ----------
def post_payment(loan: dict[str, Any], escrow_account: dict[str, Any] | None,
                 amount_cents: int, posting_strategy: str) -> dict[str, int]:
    """Return allocation dict with int cents per bucket.

    Buckets: interest_cents, principal_cents, escrow_cents, pmi_cents,
             late_fee_cents, suspense_cents
    """
    remaining = Decimal(amount_cents)
    principal_balance = Decimal(loan.get("principal_balance_cents", 0))
    escrow_monthly = Decimal(loan.get("escrow_monthly_cents", 0))
    pmi_monthly = Decimal(loan.get("pmi_monthly_cents", 0) if loan.get("pmi_required") else 0)
    outstanding_late_fees = Decimal(loan.get("outstanding_late_fees_cents", 0))

    # Per PRD §3.2: the waterfall first satisfies accrued_interest_cents and
    # second satisfies the principal portion of the oldest unpaid installment.
    # Under standard fixed-rate amortization, the interest portion of an
    # installment = principal_balance * monthly_rate, and the principal
    # portion = scheduled_monthly_pi_cents - that interest portion. The
    # loan's accrued_interest_cents bucket reflects the accrued-but-unpaid
    # interest for the current period, computed at posting time.
    interest_rate_bps = Decimal(loan.get("interest_rate_bps", 0))
    monthly_rate = interest_rate_bps / Decimal(10_000) / Decimal(12)
    accrued_interest = round_half_up(principal_balance * monthly_rate) + \
        Decimal(loan.get("accrued_interest_cents", 0))
    accrued_interest = Decimal(accrued_interest)

    interest_alloc = Decimal(0)
    principal_alloc = Decimal(0)
    escrow_alloc = Decimal(0)
    pmi_alloc = Decimal(0)
    late_fee_alloc = Decimal(0)
    suspense_alloc = Decimal(0)

    # 1. accrued interest
    take = min(remaining, accrued_interest)
    interest_alloc += take
    remaining -= take

    # 2. principal portion of the oldest unpaid installment.
    # Per PRD §3.2 / §3.1 amortization model: principal portion of one
    # installment = scheduled_monthly_pi - interest_portion_of_installment,
    # where the interest portion = principal_balance * monthly_rate.
    scheduled_pi = Decimal(loan.get("scheduled_monthly_pi_cents", 0))
    interest_portion_of_installment = round_half_up(principal_balance * monthly_rate)
    principal_portion_needed = max(Decimal(0), scheduled_pi - Decimal(interest_portion_of_installment))
    principal_portion_needed = min(principal_portion_needed, principal_balance)
    take = min(remaining, principal_portion_needed)
    principal_alloc += take
    remaining -= take

    # 3. escrow installment top-up
    take = min(remaining, escrow_monthly)
    escrow_alloc += take
    remaining -= take

    # 4. PMI premium
    take = min(remaining, pmi_monthly)
    pmi_alloc += take
    remaining -= take

    # 5. late fees (latest-posted-first, but aggregated here)
    take = min(remaining, outstanding_late_fees)
    late_fee_alloc += take
    remaining -= take

    # 6. residual handling
    # Total installment satisfied if all of interest, principal, escrow, pmi covered.
    full_installment_satisfied = (
        interest_alloc >= accrued_interest
        and principal_alloc >= principal_portion_needed
        and escrow_alloc >= escrow_monthly
        and pmi_alloc >= pmi_monthly
    )

    if posting_strategy == "PRINCIPAL_CURTAILMENT" and loan.get("status") == "CURRENT" \
            and full_installment_satisfied:
        # Surplus over installment goes directly to principal
        take = min(remaining, principal_balance - principal_alloc)
        principal_alloc += take
        remaining -= take
        # No suspense in this variant
        # If anything is left after principal fully retired, treat as principal anyway (overpayment)
        if remaining > 0:
            principal_alloc += remaining
            remaining = Decimal(0)
    else:
        # STANDARD_WATERFALL: if residual is at least one full installment short, additional principal
        # The "one full installment" is scheduled_pi + escrow + pmi.
        full_installment = scheduled_pi + escrow_monthly + pmi_monthly
        if full_installment_satisfied and remaining >= full_installment and full_installment > 0:
            # Apply additional principal curtailment chunks
            extra_principal = min(remaining, principal_balance - principal_alloc)
            principal_alloc += extra_principal
            remaining -= extra_principal
            if remaining > 0:
                suspense_alloc += remaining
                remaining = Decimal(0)
        else:
            # Less than full installment short -> SUSPENSE
            suspense_alloc += remaining
            remaining = Decimal(0)

    # Rounding occurs once at the END; partial-cent rounding remainders flow to escrow.
    # We've already used integer cents throughout (Decimal of integer cents); no fractional cents arose.
    # But to be safe, quantize each to int via half-up.
    interest_i = round_half_up(interest_alloc)
    principal_i = round_half_up(principal_alloc)
    pmi_i = round_half_up(pmi_alloc)
    late_i = round_half_up(late_fee_alloc)
    suspense_i = round_half_up(suspense_alloc)
    # escrow absorbs the rounding remainder
    escrow_i = amount_cents - interest_i - principal_i - pmi_i - late_i - suspense_i
    # Guard against negative (shouldn't happen with integer-cents arithmetic)
    if escrow_i < 0:
        # Negative remainder: pull from suspense first, then principal
        deficit = -escrow_i
        escrow_i = 0
        if suspense_i >= deficit:
            suspense_i -= deficit
            deficit = 0
        else:
            deficit -= suspense_i
            suspense_i = 0
            principal_i = max(0, principal_i - deficit)

    return {
        "interest_cents": interest_i,
        "principal_cents": principal_i,
        "escrow_cents": escrow_i,
        "pmi_cents": pmi_i,
        "late_fee_cents": late_i,
        "suspense_cents": suspense_i,
    }


# ---------- Escrow analysis ----------
def escrow_analysis(escrow_account: dict[str, Any], variant: str, as_of_date: datetime) -> dict[str, int]:
    """Return computed analysis fields:
       new_escrow_monthly_cents, projected_low_point_cents,
       required_low_point_cents, shortage_cents, surplus_cents
    """
    annual_tax = Decimal(escrow_account.get("annual_tax_cents", 0))
    annual_insurance = Decimal(escrow_account.get("annual_insurance_cents", 0))
    cushion_months = escrow_account.get("cushion_months", 2)
    annual_total = annual_tax + annual_insurance

    # required_low_point_cents = round_half_up(cushion_months * (annual_tax + annual_insurance) / 12)
    required_low_point = round_half_up(Decimal(cushion_months) * annual_total / Decimal(12))

    # ---- Variant-specific new_escrow_monthly_cents and projected_low_point ----
    if variant == "ACTUAL_TRAILING_12":
        # Sum trailing-12 PAID disbursements
        window_start = as_of_date - timedelta(days=365)
        paid_disbursements = []
        for d in db.escrow_disbursements.values():
            if d.get("escrow_account_id") != escrow_account["id"]:
                continue
            if d.get("status") != "PAID":
                continue
            paid_at = d.get("paid_at")
            if not paid_at:
                continue
            try:
                paid_dt = db.parse_ts(paid_at)
            except Exception:
                continue
            if paid_dt > window_start and paid_dt <= as_of_date:
                paid_disbursements.append((paid_dt, d.get("amount_cents", 0)))
        total_paid = sum((Decimal(a) for _, a in paid_disbursements), Decimal(0))
        new_monthly = ceil_to_cent(total_paid / Decimal(12))

        # Simulate next 12 months using new_monthly inflow & replayed trailing-12 PAID pattern outflow
        # Group outflows by month-offset from window_start (0..11)
        outflows_by_month = [Decimal(0)] * 12
        for paid_dt, amt in paid_disbursements:
            month_offset = ((paid_dt.year - window_start.year) * 12 + (paid_dt.month - window_start.month))
            month_offset = max(0, min(11, month_offset))
            outflows_by_month[month_offset] += Decimal(amt)

        balance = Decimal(escrow_account.get("balance_cents", 0))
        low_point = balance
        for m in range(12):
            balance += Decimal(new_monthly)
            balance -= outflows_by_month[m]
            if balance < low_point:
                low_point = balance
        projected_low_point = int(low_point)

    elif variant == "FORECAST_NEXT_12":
        new_monthly = round_half_up(annual_total / Decimal(12))

        # Simulate next 12 months: new_monthly inflows, SCHEDULED disbursements as outflows
        balance = Decimal(escrow_account.get("balance_cents", 0))
        # Group SCHEDULED rows into per-month buckets over the next 12 months from as_of_date
        outflows_by_month = [Decimal(0)] * 12
        for d in db.escrow_disbursements.values():
            if d.get("escrow_account_id") != escrow_account["id"]:
                continue
            if d.get("status") != "SCHEDULED":
                continue
            try:
                sched = db.parse_ts(d["scheduled_for"])
            except Exception:
                continue
            if sched <= as_of_date:
                continue
            month_offset = (sched.year - as_of_date.year) * 12 + (sched.month - as_of_date.month)
            if 0 <= month_offset < 12:
                outflows_by_month[month_offset] += Decimal(d.get("amount_cents", 0))
        low_point = balance
        for m in range(12):
            balance += Decimal(new_monthly)
            balance -= outflows_by_month[m]
            if balance < low_point:
                low_point = balance
        projected_low_point = int(low_point)

    else:
        # Defensive: should be caught upstream
        new_monthly = 0
        projected_low_point = 0

    shortage = max(0, required_low_point - projected_low_point)
    surplus = max(0, projected_low_point - required_low_point)
    if shortage > 0:
        # ceil(shortage / 12)
        add = ceil_to_cent(Decimal(shortage) / Decimal(12))
        new_monthly += add

    return {
        "new_escrow_monthly_cents": new_monthly,
        "projected_low_point_cents": projected_low_point,
        "required_low_point_cents": required_low_point,
        "shortage_cents": shortage,
        "surplus_cents": surplus,
    }


# ---------- PMI eligibility ----------
def compute_ltv_bps(loan: dict[str, Any], appraisal_value_cents: int | None) -> int:
    baseline = appraisal_value_cents if appraisal_value_cents is not None else loan.get("original_property_value_cents", 0)
    if not baseline:
        return 10000
    P = Decimal(loan.get("principal_balance_cents", 0))
    return round_half_up(P * Decimal(10000) / Decimal(baseline))


def clean_payment_history_12mo(loan_id: str) -> bool:
    """No SUSPENSE payments in trailing 12 months AND no day where days_past_due > 30 in that window."""
    now = db.utcnow()
    window_start = now - timedelta(days=CLEAN_HISTORY_WINDOW_DAYS)
    for p in db.payments.values():
        if p.get("loan_id") != loan_id:
            continue
        if p.get("status") == "SUSPENSE":
            try:
                rec = db.parse_ts(p.get("received_at", p.get("posted_at", "")))
            except Exception:
                continue
            if rec >= window_start and rec <= now:
                return False
    # Check loan's max-days-past-due flag if we track it; otherwise conservative-best check:
    # Look at the loan's max_dpd_observed in trailing 12 months — we maintain this as a derived field.
    loan = db.loans.get(loan_id)
    if loan is None:
        return False
    # We keep max_dpd_observed updated on every payment posting & clock advance
    if loan.get("max_dpd_observed_12mo", 0) > CLEAN_HISTORY_MAX_DPD:
        return False
    return True


def pmi_denial_reason(loan: dict[str, Any], computed_ltv_bps: int) -> str | None:
    """Return denial reason string per §1.3 precedence, or None if eligible.

    Precedence (first-match wins):
       1. Loan.status NOT IN {CURRENT, REINSTATED} -> IN_DELINQUENCY
       2. computed_ltv_bps >= 8000               -> LTV_TOO_HIGH
       3. clean_payment_history_12mo == False     -> PAYMENT_HISTORY_NOT_CLEAN
    """
    if loan.get("status") not in {"CURRENT", "REINSTATED"}:
        return "IN_DELINQUENCY"
    if computed_ltv_bps >= LTV_BORROWER_REQUEST_BPS:
        return "LTV_TOO_HIGH"
    if not clean_payment_history_12mo(loan["id"]):
        return "PAYMENT_HISTORY_NOT_CLEAN"
    return None


# ---------- Foreclosure cure amount ----------
def foreclosure_cure_amount(loan: dict[str, Any]) -> int:
    """cure = principal_arrears + accrued_interest + outstanding_late_fees + FORECLOSURE_FEE_FLAT_CENTS

    principal_arrears = months_past_due * scheduled_monthly_pi_cents
    months_past_due = days_past_due // 30
    """
    days_past_due = loan.get("days_past_due", 0)
    months_past_due = days_past_due // MONTHLY_DAYS
    principal_arrears = months_past_due * loan.get("scheduled_monthly_pi_cents", 0)
    accrued_interest = loan.get("accrued_interest_cents", 0)
    late_fees = loan.get("outstanding_late_fees_cents", 0)
    return principal_arrears + accrued_interest + late_fees + FORECLOSURE_FEE_FLAT_CENTS


# ---------- Forbearance deferral ----------
def forbearance_deferral(loan: dict[str, Any], start_date: datetime, end_date: datetime,
                         reduced_payment_cents: int) -> int:
    """deferred_per_month * number_of_months (inclusive month count)."""
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1
    total_monthly = loan.get("total_monthly_payment_cents", 0)
    deferred_per_month = max(0, total_monthly - reduced_payment_cents)
    return deferred_per_month * months


# ---------- days_past_due / next_due_date helpers ----------
def compute_days_past_due(loan: dict[str, Any]) -> int:
    """Recompute integer days_past_due from current simulated UTC vs next_due_date.

    Returns 0 when next_due_date is in the future. Otherwise floor(days_late).
    Forced choice (PRD ambiguity): we use floor of (now - next_due_date) total seconds / 86400.
    """
    now = db.utcnow()
    nd_raw = loan.get("next_due_date")
    if not nd_raw:
        return 0
    try:
        nd = db.parse_ts(nd_raw)
    except Exception:
        return 0
    if now <= nd:
        return 0
    delta = now - nd
    return delta.days  # floor of total days


def update_max_dpd_observed(loan: dict[str, Any]) -> None:
    """Track the maximum days_past_due observed over the loan lifetime
    (used for clean_payment_history_12mo)."""
    dpd = loan.get("days_past_due", 0)
    if dpd > loan.get("max_dpd_observed_12mo", 0):
        loan["max_dpd_observed_12mo"] = dpd
