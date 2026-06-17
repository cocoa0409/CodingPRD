"""Calculation rules (SCAFFOLD 1.3 / PRD 2.7, 3.x).

All monetary amounts are integer cents. Where a rate derives cents the result
is floored (truncated downward); intermediate rate arithmetic uses IEEE-754
double precision (plain Python float). Reputation is 2dp half-up.
"""
import math
from decimal import ROUND_HALF_UP, Decimal

# ---- platform_fee constants ----
TIER_A_CEIL = 5000000        # < 50,000.00 -> TIER_A
TIER_B_CEIL = 100000000      # < 1,000,000.00 -> TIER_B (>= TIER_A_CEIL)
TIER_A_RATE = 0.20
TIER_B_RATE = 0.10
TIER_C_RATE = 0.05
RISK_LOSS_THRESHOLD = 3
RISK_SURCHARGE = 0.05
MAX_RATE = 0.25
MIN_FEE_CENTS = 100

# ---- hourly cap ----
MINUTES_PER_HOUR = 60

# ---- daily hours cap ----
GLOBAL_DAILY_MINUTE_CAP = 720

# ---- reputation ----
COMPLETION_WEIGHT = 0.6
RATING_WEIGHT = 0.4
LOSS_PENALTY = 4
MAX_PENALTY = 40

# ---- tax ----
REPORTING_THRESHOLD_CENTS = 60000

# ---- match score ----
SKILL_W = 0.5
REP_W = 0.3
PRICE_W = 0.2


def fee_tier(lifetime_earnings_cents):
    """fee_tier enum derived from cumulative net earnings (PRD 3.6)."""
    if lifetime_earnings_cents < TIER_A_CEIL:
        return "TIER_A"
    if lifetime_earnings_cents < TIER_B_CEIL:
        return "TIER_B"
    return "TIER_C"


def platform_fee(gross_cents, lifetime_earnings_cents, dispute_loss_count):
    """Return (platform_fee_cents, net_cents) for a payout (PRD 3.6).

    Step 1: base tier rate keyed on pre-payout lifetime_earnings_cents.
    Step 2: +0.05 risk surcharge if dispute_loss_count >= 3.
    Step 3: clamp rate to MAX_RATE (0.25).
    Step 4: fee = floor(gross * rate), never below MIN_FEE_CENTS unless gross==0
            (then fee=0), and never exceeding gross.
    """
    if gross_cents == 0:
        return 0, 0

    if lifetime_earnings_cents < TIER_A_CEIL:
        rate = TIER_A_RATE
    elif lifetime_earnings_cents < TIER_B_CEIL:
        rate = TIER_B_RATE
    else:
        rate = TIER_C_RATE

    if dispute_loss_count >= RISK_LOSS_THRESHOLD:
        rate += RISK_SURCHARGE

    rate = min(rate, MAX_RATE)

    fee = math.floor(gross_cents * rate)
    if fee < MIN_FEE_CENTS:
        fee = MIN_FEE_CENTS
    if fee > gross_cents:
        fee = gross_cents
    net = gross_cents - fee
    return fee, net


def hourly_milestone_amount(verified_logs, agreed_rate_cents):
    """Recompute milestone.amount_cents from VERIFIED timelogs (PRD 3.4).

    Round per log, then sum: per_log = floor(minutes/60 * agreed_rate).
    """
    total = 0
    for log in verified_logs:
        minutes = log["billable_minutes"]
        per_log = math.floor(minutes / MINUTES_PER_HOUR * agreed_rate_cents)
        total += per_log
    return total


def reputation_score(completed_count, dispute_loss_count, avg_rating, has_reviews):
    """Weighted reputation 0-100, 2dp half-up (PRD 3.1)."""
    total_outcomes = completed_count + dispute_loss_count
    completion_rate = (completed_count / total_outcomes) if total_outcomes else 0.0
    rating_factor = (avg_rating / 5.0) if has_reviews else 0.0
    raw = (completion_rate * COMPLETION_WEIGHT) + (rating_factor * RATING_WEIGHT)
    acute_penalty = min(dispute_loss_count * LOSS_PENALTY, MAX_PENALTY)
    value = max(0.0, min(100.0, raw * 100 - acute_penalty))
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def match_score(skill_coverage, reputation, budget_cents, bid_amount_cents):
    """job_match_score for ranked proposals (PRD 3.2)."""
    rep_factor = reputation / 100.0
    price_factor = budget_cents / max(1, bid_amount_cents)
    price_factor = max(0.0, min(1.0, price_factor))
    match = skill_coverage * SKILL_W + rep_factor * REP_W + price_factor * PRICE_W
    return round(match, 4)
