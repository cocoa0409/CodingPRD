"""Pure calculation rules (no store access)."""
from decimal import Decimal

from util import floor_days, round_half_up, round_half_up_2

# --- constants ------------------------------------------------------------
LENDER_BASE_CENTS = 20000
OWNER_BASE_CENTS = 10000
ABANDONED_SURCHARGE_PCT = Decimal("0.5")

DAILY_PENALTY_CENTS = 500
TIER2_THRESHOLD_DAYS = 30
MAX_MULTIPLE = 3

LIEN_INTEREST_BPS = 1000
DAY_COUNT = 365

SUSPEND_THRESHOLD_CENTS = 100000
MIN_LIEN_CENTS = 25000
DEMOLITION_MIN_VIOLATIONS = 3
DEMOLITION_MIN_BALANCE_CENTS = 50000
ABATEMENT_BUFFER_SECONDS = 24 * 3600

ADMIN_TIER1_CAP_CENTS = 100000
ADMIN_TIER1_PCT = Decimal("0.15")
ADMIN_TIER2_PCT = Decimal("0.10")
INSPECTION_REIMB_CENTS = 5000

SEVERITY_CAP = 40
VACANCY_PT_PER_MONTH = 2
VACANCY_CAP = 20
BALANCE_CENTS_PER_POINT = 10000
BALANCE_CAP = 25
FORECLOSURE_POINTS = {
    "REO": 15,
    "AUCTION_SCHEDULED": 10,
    "LIS_PENDENS": 7,
    "NOTICE_OF_DEFAULT": 4,
    "NONE": 0,
}


def registration_fee(registration_type, occupancy_status):
    base = LENDER_BASE_CENTS if registration_type == "LENDER" else OWNER_BASE_CENTS
    if occupancy_status == "ABANDONED":
        surcharge = round_half_up(Decimal(base) * ABANDONED_SURCHARGE_PCT)
    else:
        surcharge = 0
    return base + surcharge


def fine_accrual(base_amount_cents, daily_penalty_cents, assessed_at, eval_instant):
    """Tiered fine accrual capped at MAX_MULTIPLE x base (integer cents)."""
    days_overdue = floor_days(eval_instant, assessed_at)
    if days_overdue < 0:
        days_overdue = 0
    tier1_days = min(days_overdue, TIER2_THRESHOLD_DAYS)
    tier2_days = max(days_overdue - TIER2_THRESHOLD_DAYS, 0)
    raw = (
        base_amount_cents
        + tier1_days * daily_penalty_cents
        + tier2_days * daily_penalty_cents * 2
    )
    cap = base_amount_cents * MAX_MULTIPLE
    return min(raw, cap)


def lien_payoff(principal_cents, interest_rate_bps, recorded_at, eval_instant):
    """Return (payoff_amount_cents accrued, payoff_quoted_cents quoted)."""
    days = floor_days(eval_instant, recorded_at)
    if days < 0:
        days = 0
    daily_rate = Decimal(interest_rate_bps) / Decimal(10000) / Decimal(DAY_COUNT)
    # accrued: round each day's interest, then multiply/sum.
    day_interest = round_half_up(Decimal(principal_cents) * daily_rate)
    accrued_interest = day_interest * days
    payoff_amount = principal_cents + accrued_interest
    # quoted: round once over the full period.
    quoted_interest = round_half_up(Decimal(principal_cents) * daily_rate * Decimal(days))
    payoff_quoted = principal_cents + quoted_interest
    return payoff_amount, payoff_quoted


def cost_recovery(actual_cost_cents):
    """Return (admin_fee_cents, recovered_amount_cents)."""
    if actual_cost_cents <= ADMIN_TIER1_CAP_CENTS:
        admin_fee = round_half_up(Decimal(actual_cost_cents) * ADMIN_TIER1_PCT)
    else:
        tier1 = round_half_up(Decimal(ADMIN_TIER1_CAP_CENTS) * ADMIN_TIER1_PCT)
        tier2 = round_half_up(
            Decimal(actual_cost_cents - ADMIN_TIER1_CAP_CENTS) * ADMIN_TIER2_PCT
        )
        admin_fee = tier1 + tier2
    recovered = actual_cost_cents + admin_fee + INSPECTION_REIMB_CENTS
    return admin_fee, recovered


def demolition_priority(severity_sum, registered_at, clock, outstanding_balance_cents,
                        foreclosure_status):
    severity_comp = min(severity_sum, SEVERITY_CAP)
    months_vacant = floor_days(clock, registered_at) // 30
    if months_vacant < 0:
        months_vacant = 0
    vacancy_comp = min(months_vacant * VACANCY_PT_PER_MONTH, VACANCY_CAP)
    balance_comp = min(outstanding_balance_cents // BALANCE_CENTS_PER_POINT, BALANCE_CAP)
    if balance_comp < 0:
        balance_comp = 0
    foreclosure_comp = FORECLOSURE_POINTS.get(foreclosure_status, 0)
    total = severity_comp + vacancy_comp + balance_comp + foreclosure_comp
    return round_half_up_2(Decimal(total))
