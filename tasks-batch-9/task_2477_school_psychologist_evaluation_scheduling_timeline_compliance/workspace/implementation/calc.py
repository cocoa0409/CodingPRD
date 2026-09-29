"""Pure calculation rules (PRD §2.6, §2.10, §3.3, §3.4, §3.7, §3.9)."""

import math
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

# --- statutory clock -------------------------------------------------------
STATUTORY_EVAL_DAYS = 60
AT_RISK_WINDOW_DAYS = 10
EXCLUSION_CAP_PCT = Decimal("0.30")
# floor(60 * 0.30) == 18 — a share of the BASE window, never the extended one.
EXCLUSION_AGGREGATE_CAP_DAYS = int(
    (Decimal(STATUTORY_EVAL_DAYS) * EXCLUSION_CAP_PCT).to_integral_value(rounding=ROUND_FLOOR)
)

PER_TYPE_CAP_DAYS = {
    "BREAK_CLOSURE": 14,
    "PARENT_UNAVAILABLE": 10,
    "STUDENT_ABSENT_STREAK": 7,
    "TRANSFER_IN_TRANSIT": 5,
}
EXCLUSION_TYPES = tuple(PER_TYPE_CAP_DAYS.keys())

# --- caseload points -------------------------------------------------------
BASE_POINTS = 3
EXTRA_DOMAIN_POINTS = 1
INTERPRETER_POINTS = 2
INITIAL_TYPE_POINTS = 2
REEVAL_TYPE_POINTS = 1

# --- pressure index --------------------------------------------------------
ON_TRACK_WEIGHT = Decimal("1.0")
AT_RISK_WEIGHT = Decimal("1.5")
BREACHED_WEIGHT = Decimal("2.0")

# --- selector --------------------------------------------------------------
BREACH_PENALTY = Decimal("0.25")
CONTINUITY_BONUS = Decimal("0.10")
CONTINUITY_CAP = 2

# --- compensatory minutes --------------------------------------------------
MINOR_MAX_DAYS = 5
MODERATE_MAX_DAYS = 15
SEVERITY_MULTIPLIER = {
    "MINOR": Decimal("1.0"),
    "MODERATE": Decimal("1.25"),
    "SEVERE": Decimal("1.5"),
}
DAILY_SERVICE_MINUTES = 30
WEEKLY_SERVICE_MINUTES = 150
REMEDY_MINUTES_CAP = 1800

# --- protocol order pricing ------------------------------------------------
TIER1_MIN_QTY = 25
TIER2_MIN_QTY = 100
DISTRICT_CONTRACT_DISCOUNT_PCT = Decimal("0.07")
RUSH_SURCHARGE_PCT = Decimal("0.085")
SMALL_ORDER_HANDLING_FEE_CENTS = 1250
AUTO_APPROVE_THRESHOLD_CENTS = 40000

# --- scheduling ------------------------------------------------------------
TRAVEL_BUFFER_MINUTES = 15
PARENT_NOTICE_LEAD_DAYS = 10
MAX_RESCHEDULES = 2

OPEN_ASSESSMENT_STATUSES = ("ASSIGNED", "IN_TESTING", "SCORED", "REPORT_DRAFTED")
CLOSED_COMPLIANCE_STATUSES = ("COMPLIANT_CLOSED", "BREACH_CLOSED_REMEDIED", "WAIVED")


def round_half_up(value, places):
    """Decimal round-half-up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def round_to_nearest_five(value):
    """PRD §2.10: divide by five, round the quotient half up, multiply back."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quotient = round_half_up(value / Decimal(5), 0)
    return int(quotient * 5)


def days_between(earlier, later):
    """Whole UTC calendar days, counting the earlier date as day zero."""
    return (later - earlier).days


def caseload_points(domains, interpreter_required, referral_type):
    points = BASE_POINTS
    points += (len(domains) - 1) * EXTRA_DOMAIN_POINTS
    if interpreter_required:
        points += INTERPRETER_POINTS
    points += INITIAL_TYPE_POINTS if referral_type == "INITIAL" else REEVAL_TYPE_POINTS
    return points


def urgency_weight(compliance_status):
    if compliance_status == "BREACHED":
        return BREACHED_WEIGHT
    if compliance_status == "AT_RISK":
        return AT_RISK_WEIGHT
    return ON_TRACK_WEIGHT


def compliance_posture(days_remaining):
    """PRD §2.6 step 7."""
    if days_remaining < 0:
        return "BREACHED"
    if days_remaining <= AT_RISK_WINDOW_DAYS:
        return "AT_RISK"
    return "ON_TRACK"


def severity_for(breach_days):
    if breach_days <= MINOR_MAX_DAYS:
        return "MINOR"
    if breach_days <= MODERATE_MAX_DAYS:
        return "MODERATE"
    return "SEVERE"


def compensatory_minutes(breach_days):
    """Both frozen variants of calculations.compensatory_minutes."""
    severity = severity_for(breach_days)
    multiplier = SEVERITY_MULTIPLIER[severity]
    day_basis = round_to_nearest_five(
        Decimal(breach_days) * Decimal(DAILY_SERVICE_MINUTES) * multiplier
    )
    weeks = int(math.ceil(Decimal(breach_days) / Decimal(7)))
    missed_basis = round_to_nearest_five(
        Decimal(weeks) * Decimal(WEEKLY_SERVICE_MINUTES) * multiplier
    )
    return severity, day_basis, missed_basis


def protocol_order_pricing(unit_cost_cents, quantity_requested, rush_flag):
    """PRD §3.4 — three independent HALF_UP roundings, in the pinned order."""
    if quantity_requested < TIER1_MIN_QTY:
        tier_multiplier = Decimal("1.00")
    elif quantity_requested < TIER2_MIN_QTY:
        tier_multiplier = Decimal("0.95")
    else:
        tier_multiplier = Decimal("0.90")

    unit_price_cents = int(round_half_up(Decimal(unit_cost_cents) * tier_multiplier, 0))
    base_cents = unit_price_cents * quantity_requested
    contract_discount_cents = int(
        round_half_up(Decimal(base_cents) * DISTRICT_CONTRACT_DISCOUNT_PCT, 0)
    )
    if rush_flag:
        rush_surcharge_cents = int(round_half_up(Decimal(base_cents) * RUSH_SURCHARGE_PCT, 0))
    else:
        rush_surcharge_cents = 0
    handling_fee_cents = (
        SMALL_ORDER_HANDLING_FEE_CENTS if quantity_requested < TIER1_MIN_QTY else 0
    )
    total_cost_cents = (
        base_cents - contract_discount_cents + rush_surcharge_cents + handling_fee_cents
    )
    auto_approved = total_cost_cents <= AUTO_APPROVE_THRESHOLD_CENTS
    return {
        "unit_price_cents": unit_price_cents,
        "base_cents": base_cents,
        "contract_discount_cents": contract_discount_cents,
        "rush_surcharge_cents": rush_surcharge_cents,
        "handling_fee_cents": handling_fee_cents,
        "total_cost_cents": total_cost_cents,
        "auto_approved": auto_approved,
    }
