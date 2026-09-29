"""Domain constants and every calculation described in PRD section 3."""

import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------- enum sets
MARKET_TIERS = ("GLOBAL", "NATIONAL", "REGIONAL")
ROSTER_STATUSES = ("ACTIVE", "SUSPENDED", "RETIRED")
CATEGORIES = ("BEVERAGE", "FOOTWEAR", "FINANCIAL", "AUTOMOTIVE", "GAMING", "NUTRITION")
TERRITORIES = ("DOMESTIC", "NORTH_AMERICA", "GLOBAL")
USAGE_TIERS = ("SOCIAL_ONLY", "BROADCAST", "PERPETUAL")
MORALS_TIERS = ("TIER_A", "TIER_B", "TIER_C")
DELIVERABLE_TYPES = ("SOCIAL_POST", "APPEARANCE", "SHOOT")
PLATFORMS = ("INSTAGRAM", "X", "TIKTOK", "YOUTUBE", "BROADCAST")
REVIEW_DECISIONS = ("APPROVE", "REQUEST_REVISION")
RULINGS = ("COMPLIANT", "NON_COMPLIANT")
BOOKING_OUTCOMES = ("COMPLETED", "NO_SHOW")
RENEWAL_DECISIONS = ("EXERCISE", "DECLINE")
EXPOSURE_VARIANTS = ("ROSTER_SNAPSHOT", "PIPELINE_PROJECTED")

# --------------------------------------------------------------- constants
TIER_WEIGHT = {"GLOBAL": Decimal("1.00"), "NATIONAL": Decimal("0.85"), "REGIONAL": Decimal("0.70")}
EXCLUSIVITY_PENALTY_PER_MONTH = Decimal("1.5")
EXCLUSIVITY_PENALTY_CAP = Decimal("20")
FIT_PASS_SCORE = 60

USAGE_MULTIPLIER = {"SOCIAL_ONLY": Decimal("1.00"), "BROADCAST": Decimal("1.35"), "PERPETUAL": Decimal("1.80")}
MORALS_MULTIPLIER = {"TIER_A": Decimal("1.15"), "TIER_B": Decimal("1.05"), "TIER_C": Decimal("1.00")}
TERRITORY_MULTIPLIER = {"DOMESTIC": Decimal("1.00"), "NORTH_AMERICA": Decimal("1.20"), "GLOBAL": Decimal("1.45")}
EXCLUSIVITY_UPLIFT_PCT_PER_MONTH = Decimal("0.05")
EXCLUSIVITY_UPLIFT_MONTH_CAP = 24
TRAVEL_DAY_RATE_PCT = Decimal("0.25")
CONTRACT_VALUE_CAP_MULTIPLE = Decimal("2.5")

OFFER_VALID_DAYS = 14
MAX_COUNTER_ROUNDS = 3
FEE_CAP_MULTIPLE = 8
NO_SHOW_PENALTY_PCT = Decimal("0.10")

DELIVERABLE_WEIGHT = {"SOCIAL_POST": 1, "APPEARANCE": 4, "SHOOT": 2}
ACCEPTED_DISCLOSURE_TAGS = ("#ad", "#sponsored", "#paidpartnership")

MORALS_WEIGHT = {"TIER_A": 3, "TIER_B": 2, "TIER_C": 1}
MORALS_STRICTNESS = {"TIER_A": 3, "TIER_B": 2, "TIER_C": 1}
RISK_CATEGORY_WEIGHT = 12
RISK_MORALS_WEIGHT = 8
RISK_DISCLOSURE_WEIGHT = 15
RISK_SCORE_CAP = 100

BONUS_TIER1_VALUE_FLOOR = 3000000
BONUS_TIER2_VALUE_FLOOR = 1500000
BONUS_PCT = {"TIER_1": Decimal("0.12"), "TIER_2": Decimal("0.07"), "TIER_3": Decimal("0.03"), "NONE": Decimal("0")}
MARKET_ESCALATOR = {"GLOBAL": Decimal("0.03"), "NATIONAL": Decimal("0.015"), "REGIONAL": Decimal("0")}

ACCRUAL_ENTRY_TYPES = ("TRAVEL_ACCRUAL", "REVERSAL", "PENALTY", "BONUS")
LEDGER_ENTRY_TYPES = ("TRAVEL_ACCRUAL", "REVERSAL", "PENALTY", "BONUS", "DISBURSEMENT")


# ------------------------------------------------------------------ rounding
def rhu(value, places=0):
    """Round half up, away from zero at the midpoint."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# ----------------------------------------------------------- date arithmetic
def add_months(base, months):
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = base.day
    while True:
        try:
            return _dt.date(year, month, day)
        except ValueError:
            day -= 1


def grant_end_date(start_date, exclusivity_months):
    """Inclusive last locked day: start + months - 1 day."""
    return add_months(start_date, exclusivity_months) - _dt.timedelta(days=1)


# --------------------------------------------------------- brand_fit_score
def brand_fit(opportunity, athlete, brand):
    workload_units = (
        4 * opportunity["planned_appearances"]
        + 2 * opportunity["planned_shoots"]
        + 1 * opportunity["planned_posts"]
    )
    expected_fee_cents = rhu_int(
        Decimal(athlete["base_appearance_rate_cents"]) * Decimal(workload_units) / Decimal(4)
    )
    if expected_fee_cents == 0:
        fee_alignment = Decimal(100)
    else:
        ratio = Decimal(opportunity["proposed_fee_cents"]) / Decimal(expected_fee_cents)
        if ratio > Decimal(1):
            ratio = Decimal(1)
        fee_alignment = Decimal(100) * ratio

    tier_weight = TIER_WEIGHT[athlete["market_tier"]]
    penalty = EXCLUSIVITY_PENALTY_PER_MONTH * Decimal(opportunity["exclusivity_months"])
    if penalty > EXCLUSIVITY_PENALTY_CAP:
        penalty = EXCLUSIVITY_PENALTY_CAP

    raw = (
        Decimal("0.40") * Decimal(brand["compliance_rating"])
        + Decimal("0.30") * (Decimal(100) * tier_weight)
        + Decimal("0.30") * fee_alignment
        - penalty
    )
    score = rhu_int(raw)
    score = max(0, min(100, score))
    return expected_fee_cents, score


# --------------------------------------------------- appearance_fee_engine
def fee_engine(fee_cents, usage_rights_tier, morals_clause_tier, territory,
               base_appearance_rate_cents, exclusivity_months, travel_component_cents=0):
    rights = rhu_int(
        Decimal(fee_cents)
        * USAGE_MULTIPLIER[usage_rights_tier]
        * MORALS_MULTIPLIER[morals_clause_tier]
        * TERRITORY_MULTIPLIER[territory]
    )
    months = min(exclusivity_months, EXCLUSIVITY_UPLIFT_MONTH_CAP)
    uplift = rhu_int(
        Decimal(base_appearance_rate_cents) * EXCLUSIVITY_UPLIFT_PCT_PER_MONTH * Decimal(months)
    )
    raw_value = rights + uplift + travel_component_cents
    cap = rhu_int(Decimal(fee_cents) * CONTRACT_VALUE_CAP_MULTIPLE)
    return min(raw_value, cap)


def travel_days_for(start_at, end_at, travel_buffer_hours):
    """ceil((end - start + 2 * buffer) / 24h); exact at whole-day boundaries."""
    span_seconds = Decimal((end_at - start_at).total_seconds())
    span_seconds += Decimal(2 * travel_buffer_hours * 3600)
    days = span_seconds / Decimal(86400)
    whole = int(days)
    if days > Decimal(whole):
        whole += 1
    return whole


def binding_travel_component(bookings, base_appearance_rate_cents):
    """bookings: qualifying rows already ordered created_at ASC."""
    cost_sum = rhu_int(Decimal(sum(b["travel_cost_cents"] for b in bookings)))
    total_days = sum(b["travel_days"] for b in bookings)
    allowance = rhu_int(
        Decimal(base_appearance_rate_cents) * TRAVEL_DAY_RATE_PCT * Decimal(total_days)
    )
    return cost_sum + allowance


# ------------------------------------------------------ payout_distribution
def payout_distribution(lines, binding_fee_cents, commission_pct, penalty_sum_cents):
    """lines: APPROVED deliverables ordered created_at ASC. Round per line, then sum."""
    total_weight = sum(DELIVERABLE_WEIGHT[d["type"]] for d in lines)
    line_values = []
    for line in lines:
        weight = DELIVERABLE_WEIGHT[line["type"]]
        value = rhu_int(
            Decimal(binding_fee_cents or 0) * Decimal(weight) / Decimal(total_weight)
        )
        line_values.append(value)
    gross = sum(line_values)
    commission = sum(
        rhu_int(Decimal(value) * Decimal(str(commission_pct))) for value in line_values
    )
    penalty = abs(penalty_sum_cents)
    net = gross - commission - penalty
    return line_values, gross, commission, penalty, net


# ----------------------------------------------- performance_bonus_renewal
def bonus_and_renewal(binding_fee_cents, approved_count, required_count,
                      market_tier, proposed_base_fee_cents):
    base_value_cents = binding_fee_cents
    if required_count and required_count > 0:
        approval_rate = rhu(
            Decimal(approved_count) / Decimal(required_count), 4
        )
    else:
        approval_rate = Decimal("0.0000")

    if approval_rate >= Decimal("1.0000") and base_value_cents >= BONUS_TIER1_VALUE_FLOOR:
        bonus_tier = "TIER_1"
    elif approval_rate >= Decimal("0.8000") and base_value_cents >= BONUS_TIER2_VALUE_FLOOR:
        bonus_tier = "TIER_2"
    elif approval_rate >= Decimal("0.5000"):
        bonus_tier = "TIER_3"
    else:
        bonus_tier = "NONE"

    bonus_cents = rhu_int(Decimal(base_value_cents) * BONUS_PCT[bonus_tier])
    total_value = base_value_cents + bonus_cents

    multiplier = Decimal("1.00")
    if bonus_tier == "TIER_1":
        multiplier += Decimal("0.10")
    elif bonus_tier == "TIER_2":
        multiplier += Decimal("0.05")
    multiplier += MARKET_ESCALATOR[market_tier]
    renewal_fee_cents = rhu_int(Decimal(proposed_base_fee_cents) * multiplier)

    return {
        "base_value_cents": base_value_cents,
        "approval_rate": float(approval_rate),
        "bonus_tier": bonus_tier,
        "bonus_cents": bonus_cents,
        "total_engagement_value_cents": total_value,
        "renewal_fee_cents": renewal_fee_cents,
    }
