"""Calculation rules (PRD §3 / SCAFFOLD §1.3).

All monetary quantities are integer cents. Intermediate real-number math may use
float; every committed value is rounded half-up to whole cents.
"""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    DAYS_PER_MONTH,
    SCORE_BASE,
    PAYMENT_HISTORY_PTS,
    LATE_PENALTY_PTS,
    UTILIZATION_MAX_PTS,
    AGE_CAP_MONTHS,
    AGE_PTS_PER_MONTH,
)


def round_half_up(value):
    """Round a real number to the nearest integer, half away from zero (round half up)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def monthly_rate(apr_bps):
    # apr_bps / 10000 -> decimal annual rate; / 12 -> monthly rate
    return (apr_bps / 10000.0) / 12.0


def compute_amortized_payment(principal_cents, apr_bps, term_months):
    """Level monthly payment, single round_half_up at the end (PRD §3.3)."""
    r = monthly_rate(apr_bps)
    n = term_months
    if r == 0:
        pay_exact = principal_cents / n
    else:
        factor = (1 + r) ** n
        pay_exact = principal_cents * r * factor / (factor - 1)
    return round_half_up(pay_exact)


def build_amortization_split(principal_cents, apr_bps, term_months, monthly_payment_cents):
    """Returns list of dicts: period_index, amount_due, principal_component, interest_component.

    Walk periods 1..n in order, per-line round_half_up of interest on running balance.
    Last period absorbs the remainder. (PRD §3.3)
    """
    r = monthly_rate(apr_bps)
    n = term_months
    bal = principal_cents
    rows = []
    for k in range(1, n + 1):
        interest_k = round_half_up(bal * r)
        if k < n:
            principal_k = monthly_payment_cents - interest_k
            amount_due_k = monthly_payment_cents
        else:
            principal_k = bal  # last period absorbs remainder
            amount_due_k = principal_k + interest_k
        bal = bal - principal_k
        rows.append({
            "period_index": k,
            "amount_due_cents": amount_due_k,
            "principal_component_cents": principal_k,
            "interest_component_cents": interest_k,
        })
    return rows


def allocate_payment(loan, schedules, amount_cents):
    """Waterfall allocation: (1) fees, then oldest-first per installment take
    its accrued interest then its principal, (2) interest, (3) principal. PRD §3.4.

    The interest bucket covers unpaid interest on the past-due and current
    installments (processed oldest-first); since each installment is satisfied in
    full before the next, this is equivalent to walking installments oldest-first
    and taking interest-then-principal per installment until the cash is exhausted.

    Returns dict with applied_fee_cents, applied_interest_cents, applied_principal_cents,
    overpay_cents (credited to wallet).
    Mutates schedule amount_paid_cents and statuses; mutates loan paid counters/outstanding.
    """
    remaining = amount_cents

    # Bucket 1: outstanding late fees (global, oldest-first not needed — one ledger)
    fee_balance = loan.get("outstanding_late_fee_cents", 0)
    applied_fee = min(remaining, fee_balance)
    remaining -= applied_fee
    loan["outstanding_late_fee_cents"] = fee_balance - applied_fee

    # Unpaid schedule rows oldest-first
    unpaid = sorted(
        [s for s in schedules if s["status"] in ("SCHEDULED", "LATE")],
        key=lambda s: s["period_index"],
    )

    applied_interest = 0
    applied_principal = 0
    outstanding_principal = loan["outstanding_principal_cents"]

    for s in unpaid:
        if remaining <= 0:
            break
        # (2) interest portion of this installment first
        interest_owed = max(0, s["interest_component_cents"] - s.get("_interest_paid_cents", 0))
        take_i = min(remaining, interest_owed)
        applied_interest += take_i
        remaining -= take_i
        s["_interest_paid_cents"] = s.get("_interest_paid_cents", 0) + take_i
        s["amount_paid_cents"] += take_i
        if remaining <= 0:
            break
        # (3) principal portion of this installment (capped by remaining outstanding)
        principal_room = outstanding_principal - applied_principal
        principal_owed = min(
            s["principal_component_cents"] - s.get("_principal_paid_cents", 0),
            principal_room,
        )
        principal_owed = max(0, principal_owed)
        take_p = min(remaining, principal_owed)
        applied_principal += take_p
        remaining -= take_p
        s["_principal_paid_cents"] = s.get("_principal_paid_cents", 0) + take_p
        s["amount_paid_cents"] += take_p

    loan["principal_paid_cents"] += applied_principal
    loan["interest_paid_cents"] += applied_interest
    loan["outstanding_principal_cents"] = max(
        0, loan["principal_cents"] - loan["principal_paid_cents"]
    )

    overpay = remaining  # everything left after principal -> wallet
    return {
        "applied_fee_cents": applied_fee,
        "applied_interest_cents": applied_interest,
        "applied_principal_cents": applied_principal,
        "overpay_cents": overpay,
    }


def compute_payoff(loan, schedules, days_since_last_due):
    """Dual-variant payoff (PRD §3.8).

    actual: outstanding_principal + per-diem accrued interest + outstanding late fees.
    scheduled_remaining: sum amount_due over unpaid (SCHEDULED|LATE) installments.
    """
    r = monthly_rate(loan["apr_bps"])
    outstanding = loan["outstanding_principal_cents"]
    accrued = round_half_up(outstanding * r * days_since_last_due / DAYS_PER_MONTH)
    fees = loan.get("outstanding_late_fee_cents", 0)
    payoff_amount = outstanding + accrued + fees

    scheduled_remaining = sum(
        s["amount_due_cents"]
        for s in schedules
        if s["status"] in ("SCHEDULED", "LATE")
    )
    interest_savings = scheduled_remaining - payoff_amount
    return {
        "payoff_amount_cents": payoff_amount,
        "scheduled_remaining_cents": scheduled_remaining,
        "interest_savings_cents": interest_savings,
    }


def compute_score(on_time_marks, late_marks, credit_limit_cents, balance_cents, months_since_first_funding):
    """Weighted score (PRD §3.12). Returns clamped simulated_score (300..850)."""
    payment_history = PAYMENT_HISTORY_PTS * on_time_marks - LATE_PENALTY_PTS * late_marks
    if credit_limit_cents > 0:
        util = balance_cents / credit_limit_cents
        util_pts = round_half_up((1 - min(util, 1.0)) * UTILIZATION_MAX_PTS)
    else:
        util_pts = 0
    age_pts = min(months_since_first_funding, AGE_CAP_MONTHS) * AGE_PTS_PER_MONTH
    raw = SCORE_BASE + payment_history + util_pts + age_pts
    return max(300, min(850, raw))
