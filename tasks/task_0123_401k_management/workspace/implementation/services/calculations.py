"""Pure calculation functions per SCAFFOLD §1.3.

All money is integer cents; all rounding uses ROUND_HALF_UP.
"""

from decimal import Decimal

from config import (
    MATCH_SAFE_HARBOR,
    MATCH_TIERED,
    VESTING_CLIFF,
    VESTING_GRADED,
    ABSOLUTE_LOAN_CAP_CENTS,
    LOAN_WINDOW_DAYS,
    UNIFORM_LIFETIME_TABLE,
    LOAN_ACTIVE,
    LOAN_SATISFIED,
)
from utils import days_between, round_half_up, parse_date


# ---------------------------------------------------------------------------
# vested_percent calculation (§1.3 — vested_percent)
# ---------------------------------------------------------------------------
def vested_percent(plan: dict, participant: dict, current_date: str) -> float:
    """Return vested_pct rounded to one decimal place."""
    sched = plan.get("vesting_schedule_type")
    hire = participant.get("hire_date")
    if hire is None or current_date is None:
        return 0.0
    days = days_between(hire, current_date)
    if days < 0:
        days = 0
    service_years = days // 365

    if sched == VESTING_CLIFF:
        cliff = int(plan.get("cliff_years") or 0)
        pct = 100.0 if service_years >= cliff else 0.0
    elif sched == VESTING_GRADED:
        graded = plan.get("graded_percentages") or []
        if len(graded) != 7:
            pct = 0.0
        else:
            idx = min(int(service_years), 6)
            pct = float(graded[idx])
    else:
        pct = 0.0

    # Store to one decimal place
    return round(pct, 1)


def vested_balance_cents(total_account_balance_cents: int, vested_pct: float) -> int:
    """vested_balance_cents = round_half_up(total * pct / 100)."""
    if total_account_balance_cents <= 0:
        return 0
    raw = Decimal(int(total_account_balance_cents)) * Decimal(str(vested_pct)) / Decimal(100)
    return round_half_up(raw)


# ---------------------------------------------------------------------------
# employer_match calculation (§1.3 — employer_match)
# ---------------------------------------------------------------------------
def compute_employee_amount_cents(gross_pay_cents: int, elected_deferral_pct) -> int:
    eligible = Decimal(str(elected_deferral_pct))
    if eligible > 100:
        eligible = Decimal(100)
    if eligible < 0:
        eligible = Decimal(0)
    raw = Decimal(int(gross_pay_cents)) * eligible / Decimal(100)
    return round_half_up(raw)


def _safe_harbor_match_pct(eligible_pct: Decimal) -> Decimal:
    tier1 = min(eligible_pct, Decimal("3.0"))
    tier2 = min(max(eligible_pct - Decimal("3.0"), Decimal(0)), Decimal("2.0"))
    return tier1 * Decimal("1.0") + tier2 * Decimal("0.5")


def _tiered_match_pct(eligible_pct: Decimal, brackets: list) -> Decimal:
    # brackets ordered ascending by employee_deferral_pct_up_to
    remaining = eligible_pct
    previous_cap = Decimal(0)
    match_pct = Decimal(0)
    for b in brackets:
        try:
            cap = Decimal(str(b["employee_deferral_pct_up_to"]))
            rate = Decimal(str(b["match_rate_pct"]))
        except (KeyError, TypeError, ValueError):
            continue
        band_width = cap - previous_cap
        if band_width < 0:
            band_width = Decimal(0)
        applied = min(remaining, band_width)
        if applied < 0:
            applied = Decimal(0)
        match_pct += applied * (rate / Decimal(100))
        remaining -= applied
        previous_cap = cap
        if remaining <= 0:
            break
    return match_pct


def compute_employer_match_cents(plan: dict, gross_pay_cents: int, elected_deferral_pct) -> int:
    """Raw uncapped employer match in cents (annual cap applied separately)."""
    eligible = Decimal(str(elected_deferral_pct))
    if eligible > 100:
        eligible = Decimal(100)
    if eligible < 0:
        eligible = Decimal(0)

    if plan.get("match_formula_type") == MATCH_SAFE_HARBOR:
        match_pct = _safe_harbor_match_pct(eligible)
    elif plan.get("match_formula_type") == MATCH_TIERED:
        brackets = plan.get("tiered_brackets") or []
        match_pct = _tiered_match_pct(eligible, brackets)
    else:
        match_pct = Decimal(0)

    raw = Decimal(int(gross_pay_cents)) * match_pct / Decimal(100)
    return round_half_up(raw)


# ---------------------------------------------------------------------------
# max_loan_amount calculation (§1.3 — max_loan_amount)
# ---------------------------------------------------------------------------
def highest_outstanding_in_window(loans_for_participant: list, repayments_by_loan: dict, current_date: str) -> int:
    """Walk every qualifying Loan for this participant in the past 365 days,
    and return the max outstanding principal observed.
    """
    if not loans_for_participant:
        return 0

    cur = parse_date(current_date)
    if cur is None:
        return 0
    from datetime import timedelta
    window_start = cur - timedelta(days=LOAN_WINDOW_DAYS)
    window_start_str = window_start.strftime("%Y-%m-%d")

    hi = 0
    for loan in loans_for_participant:
        status = loan.get("status")
        # Qualifies if origination_date >= window_start, OR
        # loan is ACTIVE and any LoanRepayment.posted_on >= window_start.
        origination = loan.get("origination_date")
        qualifies = False
        if origination and origination >= window_start_str:
            qualifies = True
        if status == LOAN_ACTIVE and not qualifies:
            reps = repayments_by_loan.get(loan["id"], [])
            for r in reps:
                if r.get("posted_on", "") >= window_start_str:
                    qualifies = True
                    break
        if not qualifies:
            # SATISFIED loans whose origination is within the window are caught above.
            # If origination is older than window_start but repayments span the window,
            # the spec instructs us to count too.
            reps = repayments_by_loan.get(loan["id"], [])
            for r in reps:
                if r.get("posted_on", "") >= window_start_str:
                    qualifies = True
                    break
        if not qualifies:
            continue

        if status == LOAN_ACTIVE:
            observed = int(loan.get("outstanding_principal_cents", 0))
        elif status == LOAN_SATISFIED:
            # MAX outstanding during the window = approved_amount_cents − payments before window start
            approved = int(loan.get("approved_amount_cents", 0) or 0)
            reps = repayments_by_loan.get(loan["id"], [])
            paid_before = sum(
                int(r.get("principal_cents", 0))
                for r in reps
                if r.get("posted_on", "") < window_start_str
            )
            observed = max(0, approved - paid_before)
        else:
            # REQUESTED loans never were ACTIVE; REJECTED never originated; DEFAULTED → outstanding=0
            # DEFAULTED counts max outstanding before default: approved - paid before window start.
            approved = int(loan.get("approved_amount_cents", 0) or 0)
            if approved <= 0:
                continue
            reps = repayments_by_loan.get(loan["id"], [])
            paid_before = sum(
                int(r.get("principal_cents", 0))
                for r in reps
                if r.get("posted_on", "") < window_start_str
            )
            observed = max(0, approved - paid_before)
        if observed > hi:
            hi = observed
    return hi


def max_loan_amount_cents(total_balance: int, vested_pct: float,
                          hi_outstanding_cents: int) -> int:
    vested_bal = vested_balance_cents(total_balance, vested_pct)
    raw_cap = min(vested_bal // 2, ABSOLUTE_LOAN_CAP_CENTS)
    return max(0, raw_cap - hi_outstanding_cents)


def monthly_payment_cents(approved_amount_cents: int, term_months: int) -> int:
    if term_months <= 0:
        return 0
    raw = Decimal(int(approved_amount_cents)) / Decimal(int(term_months))
    return round_half_up(raw)


# ---------------------------------------------------------------------------
# required_minimum_distribution calculation (§1.3)
# ---------------------------------------------------------------------------
def rmd_required_amount_cents(prior_year_end_balance_cents: int, age_attained: int) -> int:
    factor = UNIFORM_LIFETIME_TABLE.get(int(age_attained))
    if factor is None:
        # Defensive: pick the closest available factor (highest age in table for ages >80)
        if age_attained > max(UNIFORM_LIFETIME_TABLE.keys()):
            factor = UNIFORM_LIFETIME_TABLE[max(UNIFORM_LIFETIME_TABLE.keys())]
        else:
            factor = UNIFORM_LIFETIME_TABLE[min(UNIFORM_LIFETIME_TABLE.keys())]
    raw = Decimal(int(prior_year_end_balance_cents)) / Decimal(str(factor))
    return round_half_up(raw)
