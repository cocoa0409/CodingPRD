"""Calculation rules (§1.3 / PRD §2.8, §3.1, §3.2, §3.7, §3.8, §3.9)."""

from decimal import Decimal, ROUND_HALF_UP

# ----- route_constraint_score ------------------------------------------
W_LAND_USE = Decimal("0.25")
W_ENVIRONMENTAL = Decimal("0.35")
W_CULTURAL = Decimal("0.25")
W_ENGINEERING = Decimal("0.15")
BASE_SCORE_CAP = Decimal("4.50")
DENSITY_LIMIT = Decimal("4.00")
VOLTAGE_MULTIPLIER = {
    "KV_138": Decimal("1.00"),
    "KV_345": Decimal("1.15"),
    "KV_500": Decimal("1.30"),
}

# ----- need_justification_margin ---------------------------------------
NEED_MARGIN_THRESHOLD = Decimal("1.1500")
MIN_SCREENED_IN_ALTERNATIVES = 2

# ----- easement_compensation -------------------------------------------
ESCALATION = {1: Decimal("1.00"), 2: Decimal("1.05"), 3: Decimal("1.12")}
STATUTORY_INTEREST_RATE = Decimal("0.06")
MAX_OFFER_ROUNDS = 3

# ----- mitigation_escrow_requirement -----------------------------------
TIER_2_FLOOR_CENTS = 500000000
TIER_3_FLOOR_CENTS = 2000000000
TIER_RATE = {"TIER_1": Decimal("0.10"), "TIER_2": Decimal("0.14"), "TIER_3": Decimal("0.18")}
HEAVY_CONDITION_WEIGHT = 4
CONDITION_SURCHARGE_CENTS = 2500000

# ----- certificate_compliance_index ------------------------------------
SEVERITY_POINTS = {"MINOR": Decimal("4"), "MAJOR": Decimal("12"), "SEVERE": Decimal("30")}
WEIGHT_STEP = Decimal("0.2")
CORRECTION_CREDIT_FACTOR = Decimal("0.5")
STOP_WORK_FLOOR = Decimal("60.00")
REVOCATION_FLOOR = Decimal("25.00")
CLOSEOUT_FLOOR = Decimal("75.00")

# ----- project_schedule_posture ----------------------------------------
AT_RISK_SLACK_DAYS = 180

# ----- application -----------------------------------------------------
FILING_FEE_MIN_CENTS = 2500000
FILING_PERIOD_DAYS = 365
EVIDENTIARY_SUSPENSION_DAYS = 90
RESCISSION_WINDOW_DAYS = 30
MAX_AMENDMENT_ROUNDS = 2
MAX_REFINEMENT_ROUNDS = 3


def D(value):
    """Decimal from an int/float/Decimal without binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


# --------------------------------------------------- levelized cost ----
def levelized_alternative_cost(capex_cents, deliverable_mw):
    return round_half_up(D(capex_cents) / D(deliverable_mw), 2)


# ----------------------------------------------------- need margin ----
def transmission_levelized(transmission_capex_cents, reliability_deficit_mw):
    return round_half_up(D(transmission_capex_cents) / D(reliability_deficit_mw), 2)


def benefit_ratio(benefit_pv_cents, transmission_capex_cents):
    return round_half_up(D(benefit_pv_cents) / D(transmission_capex_cents), 4)


def need_margin_ratio(selected_levelized, transmission_lev, benefit):
    return round_half_up((D(selected_levelized) / D(transmission_lev)) * D(benefit), 4)


# ------------------------------------------- route constraint score ----
def _effective_ratings(segment, variant):
    land = D(segment["land_use_rating"])
    env = D(segment["environmental_rating"])
    cul = D(segment["cultural_rating"])
    eng = D(segment["engineering_rating"])
    if variant == "CERTIFIED" and segment["survey_status"] == "DESKTOP":
        env = D(5)
        cul = D(5)
    return land, env, cul, eng


def _variant_score(segments, variant, voltage_multiplier):
    total = Decimal("0")
    for segment in segments:
        land, env, cul, eng = _effective_ratings(segment, variant)
        base = W_LAND_USE * land + W_ENVIRONMENTAL * env + W_CULTURAL * cul + W_ENGINEERING * eng
        if base > BASE_SCORE_CAP:
            base = BASE_SCORE_CAP
        seg_score = round_half_up(D(segment["miles"]) * base * voltage_multiplier, 2)
        total = total + seg_score
    return round_half_up(total, 2)


def route_constraint_score(project, segments):
    """Returns (preliminary, certified, total_miles, density_certified)."""
    ordered = sorted(segments, key=lambda s: s["sequence_index"])
    multiplier = VOLTAGE_MULTIPLIER[project["voltage_class"]]
    preliminary = _variant_score(ordered, "PRELIMINARY", multiplier)
    certified = _variant_score(ordered, "CERTIFIED", multiplier)
    total_miles = round_half_up(sum((D(s["miles"]) for s in ordered), Decimal("0")), 2)
    density = None
    if total_miles > 0:
        density = round_half_up(certified / total_miles, 2)
    return preliminary, certified, total_miles, density


def total_miles_of(segments):
    return round_half_up(sum((D(s["miles"]) for s in segments), Decimal("0")), 2)


# ------------------------------------------------ easement valuation ----
def negotiated_offer_cents(tract, offer_round):
    land_value = cents(D(tract["acres"]) * D(tract["per_acre_value_cents"]) * D(tract["easement_factor"]))
    base_offer = land_value + int(tract.get("structure_damages_cents") or 0)
    escalation = ESCALATION[offer_round]
    return cents(D(base_offer) * escalation)


def condemnation_award_cents(tract):
    before = int(tract.get("before_value_cents") or 0)
    after = int(tract.get("after_value_cents") or 0)
    diminution = before - after
    deposit_interest = cents(D(int(tract.get("deposit_cents") or 0)) * STATUTORY_INTEREST_RATE)
    return diminution + int(tract.get("severance_damages_cents") or 0) + deposit_interest


# ------------------------------------------------------ escrow tier ----
def escrow_tier_for(mitigation_base_cents):
    if mitigation_base_cents < TIER_2_FLOOR_CENTS:
        return "TIER_1"
    if mitigation_base_cents < TIER_3_FLOOR_CENTS:
        return "TIER_2"
    return "TIER_3"


def mitigation_escrow(mitigation_base_cents, conditions):
    tier = escrow_tier_for(mitigation_base_cents)
    contingency = cents(D(mitigation_base_cents) * TIER_RATE[tier])
    heavy = sum(1 for c in conditions if int(c["severity_weight"]) >= HEAVY_CONDITION_WEIGHT)
    surcharge = CONDITION_SURCHARGE_CENTS * heavy
    required = mitigation_base_cents + contingency + surcharge
    return tier, contingency, surcharge, required


# ------------------------------------------------- compliance index ----
def deduction_points(severity, severity_weight):
    factor = Decimal("1") + WEIGHT_STEP * (D(severity_weight) - Decimal("1"))
    return round_half_up(SEVERITY_POINTS[severity] * factor, 2)


def compliance_indices(findings):
    rolling_sum = Decimal("0")
    cumulative_sum = Decimal("0")
    for finding in findings:
        if finding["status"] not in ("OPEN", "CORRECTED"):
            continue
        points = D(finding["deduction_points"])
        cumulative_sum += points
        rolling_sum += points if finding["status"] == "OPEN" else points * CORRECTION_CREDIT_FACTOR
    rolling = round_half_up(Decimal("100") - rolling_sum, 2)
    cumulative = round_half_up(Decimal("100") - cumulative_sum, 2)
    zero = Decimal("0.00")
    return max(zero, rolling), max(zero, cumulative)


def derived_posture(rolling, cumulative):
    if D(cumulative) < REVOCATION_FLOOR:
        return "REVOKED"
    if D(rolling) < STOP_WORK_FLOOR:
        return "STOP_WORK"
    return "ACTIVE"
