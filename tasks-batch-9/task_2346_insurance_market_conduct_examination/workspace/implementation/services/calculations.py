"""Every statutory calculation of PRD §3, with the pinned rounding orders."""

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
HIGH_TIER_RATIO = Decimal("5.00")
ELEVATED_TIER_RATIO = Decimal("2.50")
MODERATE_TIER_RATIO = Decimal("1.00")

FINANCIAL_WEIGHT = Decimal("0.30")
FINANCIAL_CAP = Decimal("30.00")
TREND_WEIGHT = Decimal("0.20")
TREND_CAP = Decimal("30.00")
LARGE_PREMIUM_THRESHOLD_CENTS = 5000000000
LARGE_PREMIUM_MULTIPLIER = Decimal("1.10")
NORMAL_MULTIPLIER = Decimal("1.00")
COMPOSITE_CAP = Decimal("100.00")

MIN_COMPOSITE_SCORE_DEFAULT = Decimal("40.00")
DEPARTMENT_STATE_CODE = "NV"

LATE_PENALTY_PCT_PER_DAY = Decimal("0.50")
ACCEPTANCE_COMPLETENESS_PCT = Decimal("95.00")
DATA_CALL_BUFFER_DAYS = 3

AREA_PREFIX = {
    "UNDERWRITING": "UW",
    "RATING": "RT",
    "CLAIMS": "CLM",
    "PRODUCER": "PRD",
}
MIN_SAMPLE_SIZE_ON_SITE = 10
MIN_SAMPLE_SIZE_DESK = 5

MATERIAL_ESCALATION_PCT = Decimal("10.00")
AREA_TOLERANCE_DEFAULTS = {
    "UNDERWRITING": Decimal("7.00"),
    "RATING": Decimal("5.00"),
    "CLAIMS": Decimal("3.00"),
    "PRODUCER": Decimal("10.00"),
}

PER_UNIT_PENALTY_CENTS = 25000
TIER1_WIDTH_CENTS = 5000000
TIER1_RATE = Decimal("0.10")
TIER2_WIDTH_CENTS = 20000000
TIER2_RATE = Decimal("0.06")
TIER3_RATE = Decimal("0.03")
BASE_PER_SUSTAINED_CRITICISM_CENTS = 100000
CREDIT_TIER_THRESHOLD_CENTS = 25000000
LOW_CREDIT_PCT = Decimal("0.05")
HIGH_CREDIT_PCT = Decimal("0.15")
STATUTORY_CAP_CENTS = 50000000

MAX_RESPONSE_ROUNDS = 3

FOLLOWUP_MONTHS_EGREGIOUS = 12
FOLLOWUP_MONTHS_MATERIAL = 18
FOLLOWUP_MONTHS_MINOR = 24
FOLLOWUP_WINDOW_DAYS = 60

TWO_PLACES = Decimal("0.01")
WHOLE = Decimal("1")


def round_half_up(value, places=2):
    exponent = TWO_PLACES if places == 2 else Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(Decimal(value).quantize(WHOLE, rounding=ROUND_HALF_UP))


# ------------------------------------------------ complaint_ratio_per_1k (§3.1)
def complaint_ratio_and_tier(policy_count_in_force, confirmed_complaints_12mo):
    if policy_count_in_force == 0:
        return Decimal("0.00"), "UNRATED"
    ratio = round_half_up(
        Decimal(confirmed_complaints_12mo * 1000) / Decimal(policy_count_in_force), 2
    )
    if ratio >= HIGH_TIER_RATIO:
        tier = "HIGH"
    elif ratio >= ELEVATED_TIER_RATIO:
        tier = "ELEVATED"
    elif ratio >= MODERATE_TIER_RATIO:
        tier = "MODERATE"
    else:
        tier = "LOW"
    return ratio, tier


# --------------------------------------------- composite_analysis_score (§3.2)
def composite_analysis_score(ratio, financial_stress_score, consumer_trend_score,
                             annual_premium_written_cents):
    if ratio >= HIGH_TIER_RATIO:
        complaint_component = Decimal("40.00")
    elif ratio >= ELEVATED_TIER_RATIO:
        complaint_component = Decimal("28.00")
    elif ratio >= MODERATE_TIER_RATIO:
        complaint_component = Decimal("16.00")
    else:
        complaint_component = Decimal("6.00")
    financial_component = min(
        FINANCIAL_CAP, round_half_up(Decimal(financial_stress_score) * FINANCIAL_WEIGHT, 2)
    )
    trend_component = min(
        TREND_CAP, round_half_up(Decimal(consumer_trend_score) * TREND_WEIGHT, 2)
    )
    volume_multiplier = (
        LARGE_PREMIUM_MULTIPLIER
        if annual_premium_written_cents >= LARGE_PREMIUM_THRESHOLD_CENTS
        else NORMAL_MULTIPLIER
    )
    # Pinned order: round each component first, sum, multiply, round, then cap.
    component_sum = complaint_component + financial_component + trend_component
    composite = min(
        COMPOSITE_CAP, round_half_up(component_sum * volume_multiplier, 2)
    )
    return {
        "complaint_component": complaint_component,
        "financial_component": financial_component,
        "trend_component": trend_component,
        "volume_multiplier": volume_multiplier,
        "composite_score": composite,
    }


# ----------------------------------------------- data_call_completeness (§3.4)
def data_call_completeness(records_received, records_requested, days_late):
    completeness = round_half_up(
        Decimal(records_received * 100) / Decimal(records_requested), 2
    )
    penalised = round_half_up(
        completeness - LATE_PENALTY_PCT_PER_DAY * Decimal(days_late), 2
    )
    effective = max(Decimal("0.00"), penalised)
    return completeness, effective


# ---------------------------------------------------- sample_draw_plan (§3.5)
def sample_draw_interval(population_size, sample_size):
    return population_size // sample_size


def sample_plan(area):
    """Deterministic (population_index, file_reference) pairs for an area."""
    interval = sample_draw_interval(area["population_size"], area["sample_size"])
    prefix = AREA_PREFIX[area["area"]]
    plan = []
    for k in range(area["sample_size"]):
        population_index = 1 + k * interval
        plan.append((population_index, "%s-%06d" % (prefix, population_index)))
    return interval, plan


# --------------------------------------------- error_rate_and_tolerance (§3.5)
def error_rates(reviewed_sample_count, error_count, material_error_count):
    if reviewed_sample_count == 0:
        return Decimal("0.00"), Decimal("0.00")
    error_rate = round_half_up(
        Decimal(error_count * 100) / Decimal(reviewed_sample_count), 2
    )
    material_rate = round_half_up(
        Decimal(material_error_count * 100) / Decimal(reviewed_sample_count), 2
    )
    return error_rate, material_rate


# ------------------------------------------------- restitution_exposure (§3.6)
def restitution_exposure(severity, tolerance_breached, sample_underpaid_total_cents,
                         reviewed_sample_count, population_size):
    if severity == "EGREGIOUS" or (severity == "MATERIAL" and tolerance_breached):
        # Pinned order: round the per-file average to whole cents FIRST,
        # then multiply by the population.
        average = round_cents(
            Decimal(sample_underpaid_total_cents) / Decimal(reviewed_sample_count)
        )
        return "POPULATION_EXTRAPOLATED", average * population_size
    return "SAMPLE_ACTUAL", sample_underpaid_total_cents


# ------------------------------------------------ penalty_determination (§3.8)
def penalty_gross(variant, restitution_cents, penalty_units_total,
                  sustained_criticism_count):
    if variant == "PER_VIOLATION":
        return penalty_units_total * PER_UNIT_PENALTY_CENTS
    tier1 = min(restitution_cents, TIER1_WIDTH_CENTS)
    tier2 = min(max(restitution_cents - TIER1_WIDTH_CENTS, 0), TIER2_WIDTH_CENTS)
    tier3 = max(restitution_cents - TIER1_WIDTH_CENTS - TIER2_WIDTH_CENTS, 0)
    return (
        round_cents(Decimal(tier1) * TIER1_RATE)
        + round_cents(Decimal(tier2) * TIER2_RATE)
        + round_cents(Decimal(tier3) * TIER3_RATE)
        + sustained_criticism_count * BASE_PER_SUSTAINED_CRITICISM_CENTS
    )


def penalty_chain(variant, restitution_cents, penalty_units_total,
                  sustained_criticism_count):
    """The five pinned steps; the credit tier is keyed on the GROSS subtotal."""
    gross = penalty_gross(
        variant, restitution_cents, penalty_units_total, sustained_criticism_count
    )
    subtotal = restitution_cents + gross
    credit = (
        HIGH_CREDIT_PCT if subtotal >= CREDIT_TIER_THRESHOLD_CENTS else LOW_CREDIT_PCT
    )
    net = round_cents(Decimal(gross) * (Decimal("1") - credit))
    return {
        "penalty_gross_cents": gross,
        "cooperation_credit_pct": credit.quantize(TWO_PLACES),
        "penalty_net_cents": net,
        "order_total_cents": restitution_cents + net,
    }


# ------------------------------------------------- lead_state_selection (§3.9)
def elect_lead_state(participating_states):
    eligible = [p for p in participating_states if p.get("has_examiner_resources")]
    if not eligible:
        return None
    ranked = sorted(eligible, key=lambda p: (-p["policy_count_in_state"], p["state_code"]))
    return ranked[0]["state_code"]


# --------------------------------- multistate_restitution_allocation (§3.9)
def allocate_restitution(participating_states, total_cents):
    denominator = sum(p["policy_count_in_state"] for p in participating_states)
    shares = {}
    for participant in participating_states:
        shares[participant["state_code"]] = (
            total_cents * participant["policy_count_in_state"]
        ) // denominator
    remainder = total_cents - sum(shares.values())
    order = sorted(
        participating_states,
        key=lambda p: (-p["policy_count_in_state"], p["state_code"]),
    )
    for participant in order[:remainder]:
        shares[participant["state_code"]] += 1
    return shares


# ---------------------------------------------------- followup_schedule (§3.10)
SEVERITY_RANK = {"MINOR": 1, "MATERIAL": 2, "EGREGIOUS": 3}
FOLLOWUP_MONTHS = {
    "EGREGIOUS": FOLLOWUP_MONTHS_EGREGIOUS,
    "MATERIAL": FOLLOWUP_MONTHS_MATERIAL,
    "MINOR": FOLLOWUP_MONTHS_MINOR,
}


def followup_months(sustained_severities):
    if not sustained_severities:
        return None
    worst = max(sustained_severities, key=lambda s: SEVERITY_RANK[s])
    return FOLLOWUP_MONTHS[worst]


def minimum_sample_size(mode):
    return MIN_SAMPLE_SIZE_ON_SITE if mode == "ON_SITE" else MIN_SAMPLE_SIZE_DESK
