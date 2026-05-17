"""Pure-function calculators (amortization, waterfall, escrow projection, etc.).

All money values are integer cents.  All rounding/ceil happens at the documented
final output; intermediate computation uses Decimal with high precision so the
final round is faithful.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from typing import Iterable, List

from config import (
    CUSHION_MONTHS,
    LATE_FEE_CAP_CENTS,
    LATE_FEE_PER_MONTH_CENTS,
    PROJECTION_WINDOW_DAYS,
)
from utils import (
    add_months,
    ceil_decimal,
    ceil_div,
    days_between,
    floor_div,
    midnight_utc,
    round_half_up,
)

# High-precision context for amortization (lots of compounding).
getcontext().prec = 60


# ───────────────────────────────────────────────────────────────────────────
# Standard mortgage amortization
# ───────────────────────────────────────────────────────────────────────────


def monthly_pi_payment(principal_cents: int, interest_rate_bps: int, term_months: int) -> int:
    """Standard mortgage payment formula, rounded half-up to whole cents.

    The PRD §3.1 says:
      - if rate==0: payment = ceil(P / n)
      - else:       payment = round_half_up(P * r * (1+r)^n / ((1+r)^n - 1))
    """
    if term_months <= 0:
        raise ValueError("term_months must be positive")
    if interest_rate_bps == 0:
        return ceil_div(principal_cents, term_months)
    r = Decimal(interest_rate_bps) / Decimal(10000) / Decimal(12)
    n = term_months
    one_plus_r_n = (Decimal(1) + r) ** n
    payment = Decimal(principal_cents) * r * one_plus_r_n / (one_plus_r_n - Decimal(1))
    return round_half_up(payment)


def per_installment_interest_cents(principal_balance_cents: int, interest_rate_bps: int) -> int:
    """Interest accrued for one monthly installment, FLOORED to whole cents.

    Per PRD §2.8: "Per-installment interest within the payment waterfall is
    computed as the floor of the principal balance times the monthly rate so
    cents-of-interest never round up against the borrower."
    """
    r = Decimal(interest_rate_bps) / Decimal(10000) / Decimal(12)
    interest = Decimal(principal_balance_cents) * r
    # Floor for positive values.
    if interest >= 0:
        return int(interest)
    return int(interest) - (1 if interest != int(interest) else 0)


# ───────────────────────────────────────────────────────────────────────────
# Late fees
# ───────────────────────────────────────────────────────────────────────────


def outstanding_late_fees_cents(delinquency_days: int) -> int:
    """Late fees = floor(delinquency_days/30) * 5000, capped at 25000."""
    if delinquency_days <= 0:
        return 0
    months_late = floor_div(delinquency_days, 30)
    fee = months_late * LATE_FEE_PER_MONTH_CENTS
    return min(fee, LATE_FEE_CAP_CENTS)


# ───────────────────────────────────────────────────────────────────────────
# Past-due installment expansion
# ───────────────────────────────────────────────────────────────────────────


def past_due_installments(loan: dict, as_of: datetime) -> List[dict]:
    """Project the list of overdue installments as of `as_of`.

    An installment is identified by its due_date (each one month apart starting
    at `next_due_date`).  An installment is included if its due_date <= as_of.
    For each installment we compute:
      - interest_due_cents  : per-installment interest at the *initial* loan
                              balance projection point.  We simulate principal
                              amortization across the unpaid installments using
                              the loan's *current* principal_balance and rate
                              so that the interest reflects what the borrower
                              still owes.
      - principal_due_cents : scheduled_payment_cents - interest_due_cents
                              (clamped to non-negative)
      - escrow_due_cents    : monthly_escrow_payment_cents
      - due_date            : the installment due date (UTC midnight)
    """
    installments: List[dict] = []
    next_due = loan["next_due_date"]
    as_of_m = midnight_utc(as_of)
    cur_due = next_due
    sim_balance = loan["principal_balance_cents"]
    sched = loan["scheduled_payment_cents"]
    escrow = loan["monthly_escrow_payment_cents"]
    rate_bps = loan["interest_rate_bps"]
    # Safety cap to avoid infinite loops on test misuse.
    safety = 0
    while midnight_utc(cur_due) <= as_of_m and safety < 600:
        safety += 1
        interest = per_installment_interest_cents(sim_balance, rate_bps)
        principal_part = sched - interest
        if principal_part < 0:
            principal_part = 0
        installments.append(
            {
                "due_date": cur_due,
                "interest_due_cents": interest,
                "principal_due_cents": principal_part,
                "escrow_due_cents": escrow,
            }
        )
        sim_balance = max(0, sim_balance - principal_part)
        cur_due = add_months(cur_due, 1)
    return installments


# ───────────────────────────────────────────────────────────────────────────
# Payment allocation waterfall (standard variant)
# ───────────────────────────────────────────────────────────────────────────


def standard_waterfall(loan: dict, amount_cents: int, received_date: datetime) -> dict:
    """Returns allocation dict + per-installment satisfaction info."""
    installments = past_due_installments(loan, received_date)

    # Aggregate demand.
    interest_due = sum(i["interest_due_cents"] for i in installments)
    principal_due = sum(i["principal_due_cents"] for i in installments)
    escrow_due = sum(i["escrow_due_cents"] for i in installments)

    delinquency_days = loan["delinquency_days"]
    late_fee_due = outstanding_late_fees_cents(delinquency_days)

    remaining = amount_cents
    alloc_late = min(remaining, late_fee_due)
    remaining -= alloc_late
    alloc_interest = min(remaining, interest_due)
    remaining -= alloc_interest
    alloc_principal = min(remaining, principal_due)
    remaining -= alloc_principal
    alloc_escrow = min(remaining, escrow_due)
    remaining -= alloc_escrow
    alloc_suspense = remaining

    # Determine how many installments are *fully* satisfied (P+I+E covered).
    # An installment is fully satisfied iff the cumulative interest + principal
    # + escrow paid covers it through the end of that installment.
    int_paid = alloc_interest
    prin_paid = alloc_principal
    esc_paid = alloc_escrow
    fully_satisfied_count = 0
    for inst in installments:
        i_demand = inst["interest_due_cents"]
        p_demand = inst["principal_due_cents"]
        e_demand = inst["escrow_due_cents"]
        if int_paid >= i_demand and prin_paid >= p_demand and esc_paid >= e_demand:
            int_paid -= i_demand
            prin_paid -= p_demand
            esc_paid -= e_demand
            fully_satisfied_count += 1
        else:
            break

    return {
        "allocation_late_fee_cents": alloc_late,
        "allocation_interest_cents": alloc_interest,
        "allocation_principal_cents": alloc_principal,
        "allocation_escrow_cents": alloc_escrow,
        "allocation_suspense_cents": alloc_suspense,
        "satisfied_installments": fully_satisfied_count,
        "installment_count": len(installments),
    }


def reinstatement_waterfall(
    loan: dict,
    case: dict,
    amount_cents: int,
    received_date: datetime,
) -> dict:
    """Foreclosure-reinstatement variant: foreclosure_costs first, then standard order.

    Settles ALL past-due installments + foreclosure_costs_cents in one go.
    """
    installments = past_due_installments(loan, received_date)
    interest_due = sum(i["interest_due_cents"] for i in installments)
    principal_due = sum(i["principal_due_cents"] for i in installments)
    escrow_due = sum(i["escrow_due_cents"] for i in installments)
    delinquency_days = loan["delinquency_days"]
    late_fee_due = outstanding_late_fees_cents(delinquency_days)
    foreclosure_costs = case.get("foreclosure_costs_cents", 0)

    remaining = amount_cents
    # Reinstatement order: foreclosure_costs → late_fee → interest → principal → escrow → suspense
    # Foreclosure costs are paid out-of-band (do not appear in the per-payment allocation buckets
    # except implicitly via reduced remaining).  We still expose them separately.
    fc_paid = min(remaining, foreclosure_costs)
    remaining -= fc_paid
    alloc_late = min(remaining, late_fee_due)
    remaining -= alloc_late
    alloc_interest = min(remaining, interest_due)
    remaining -= alloc_interest
    alloc_principal = min(remaining, principal_due)
    remaining -= alloc_principal
    alloc_escrow = min(remaining, escrow_due)
    remaining -= alloc_escrow
    alloc_suspense = remaining

    return {
        "foreclosure_costs_paid_cents": fc_paid,
        "allocation_late_fee_cents": alloc_late,
        "allocation_interest_cents": alloc_interest,
        "allocation_principal_cents": alloc_principal,
        "allocation_escrow_cents": alloc_escrow,
        "allocation_suspense_cents": alloc_suspense,
        "satisfied_installments": len(installments),
        "installment_count": len(installments),
    }


# ───────────────────────────────────────────────────────────────────────────
# Escrow projection
# ───────────────────────────────────────────────────────────────────────────


def escrow_projection(
    loan: dict,
    analysis_date: datetime,
    starting_balance_cents: int,
    disbursements: Iterable[dict],
) -> dict:
    """Return projected_disbursements, required_cushion, shortage, surplus, new_monthly_escrow.

    Inputs:
      disbursements: iterable of Disbursement dicts (all on this loan).
    """
    window_start = midnight_utc(analysis_date)
    window_end = window_start + timedelta(days=PROJECTION_WINDOW_DAYS)

    projected = 0
    for d in disbursements:
        if d["status"] != "SCHEDULED":
            continue
        if d["type"] not in ("PROPERTY_TAX", "HAZARD_INSURANCE"):
            continue
        sd = midnight_utc(d["scheduled_date"])
        if window_start <= sd < window_end:
            projected += d["amount_cents"]
    # Add PMI if active.
    if loan["pmi_status"] == "ACTIVE":
        projected += loan["pmi_monthly_cents"] * 12

    # required_cushion = ceil(projected / 12) * 2
    required_cushion = ceil_div(projected, 12) * CUSHION_MONTHS
    shortage = max(0, required_cushion - starting_balance_cents)
    surplus = max(0, starting_balance_cents - (required_cushion + projected))
    new_monthly_escrow = ceil_div(projected + shortage, 12)

    return {
        "projected_disbursements_cents": projected,
        "required_cushion_cents": required_cushion,
        "shortage_cents": shortage,
        "surplus_cents": surplus,
        "new_monthly_escrow_cents": new_monthly_escrow,
    }


# ───────────────────────────────────────────────────────────────────────────
# PMI LTV evaluation
# ───────────────────────────────────────────────────────────────────────────


def evaluate_ltv_bps(principal_balance_cents: int, basis_value_cents: int) -> int:
    """floor((principal * 10000) / basis_value)."""
    if basis_value_cents <= 0:
        raise ValueError("basis_value_cents must be positive")
    return floor_div(principal_balance_cents * 10000, basis_value_cents)


# ───────────────────────────────────────────────────────────────────────────
# Reinstatement quote
# ───────────────────────────────────────────────────────────────────────────


def reinstatement_quote_cents(loan: dict, case: dict, as_of: datetime) -> int:
    """sum(past-due P&I + escrow) + outstanding late fees + foreclosure_costs + escrow shortage."""
    installments = past_due_installments(loan, as_of)
    pi_plus_escrow = 0
    for i in installments:
        pi_plus_escrow += i["interest_due_cents"] + i["principal_due_cents"] + i["escrow_due_cents"]
    late_fees = outstanding_late_fees_cents(loan["delinquency_days"])
    foreclosure_costs = case.get("foreclosure_costs_cents", 0)
    escrow_shortage = max(0, -loan["escrow_balance_cents"])
    return pi_plus_escrow + late_fees + foreclosure_costs + escrow_shortage


# ───────────────────────────────────────────────────────────────────────────
# HAMP modified payment
# ───────────────────────────────────────────────────────────────────────────


def hamp_modified_payment(
    loan: dict,
    origination_to_now_months: int,
    offered_new_rate_bps,
    offered_term_extension_months: int,
    offered_principal_forbearance_cents: int,
) -> dict:
    """Compute target_payment_cents and the affordability floor.

    Returns dict with: target_payment_cents, floor_payment_cents, p_remaining,
    n_new, rate_bps_used.
    """
    p_remaining = loan["principal_balance_cents"] - offered_principal_forbearance_cents
    rate_bps_used = offered_new_rate_bps if offered_new_rate_bps is not None else loan["interest_rate_bps"]
    n_new = (loan["term_months"] - origination_to_now_months) + offered_term_extension_months

    if n_new <= 0:
        # Avoid divide-by-zero; treat as ineligible affordability floor.
        return {
            "target_payment_cents": -1,
            "floor_payment_cents": -1,
            "p_remaining": p_remaining,
            "n_new": n_new,
            "rate_bps_used": rate_bps_used,
        }

    if rate_bps_used == 0:
        target = ceil_div(p_remaining, n_new) if p_remaining > 0 else 0
    else:
        r = Decimal(rate_bps_used) / Decimal(10000) / Decimal(12)
        one_plus_r_n = (Decimal(1) + r) ** n_new
        target_dec = Decimal(p_remaining) * r * one_plus_r_n / (one_plus_r_n - Decimal(1))
        target = ceil_decimal(target_dec)

    floor_payment = ceil_div(p_remaining, n_new) if p_remaining > 0 else 0

    return {
        "target_payment_cents": int(target),
        "floor_payment_cents": int(floor_payment),
        "p_remaining": p_remaining,
        "n_new": n_new,
        "rate_bps_used": rate_bps_used,
    }
