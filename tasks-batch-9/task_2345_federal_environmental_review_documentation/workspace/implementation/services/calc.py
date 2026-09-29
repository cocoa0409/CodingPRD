"""All arithmetic rules (PRD 2.8, 3.3, 3.4, 3.7, 3.9 and SCAFFOLD calculations)."""

from decimal import Decimal, ROUND_HALF_UP

import db

TEMPORAL_FACTOR = {
    "PAST": Decimal("0.75"),
    "PRESENT": Decimal("1.00"),
    "REASONABLY_FORESEEABLE": Decimal("0.85"),
}

FOOTPRINT_DIVISOR = Decimal("200.0")
FOOTPRINT_WEIGHT_CAP = Decimal("0.5")
CROWDING_FREE_ENTRIES = 3
CROWDING_STEP = Decimal("0.05")

CUMULATIVE_UPLIFT_RATE = Decimal("0.15")
CUMULATIVE_UPLIFT_FLOOR = Decimal("40.0")
SCORE_CEILING = Decimal("100.0")

ALIGNMENT_WEIGHT = Decimal("0.65")
COST_WEIGHT = Decimal("0.35")

FEE_RATE_HIGH = Decimal("0.05")
FEE_RATE_MID = Decimal("0.035")
FEE_RATE_LOW = Decimal("0.02")
FEE_TIER_HIGH_POINTS = Decimal("10.00")
FEE_TIER_MID_POINTS = Decimal("5.00")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=2):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def r2(value):
    """Two-decimal, round-half-up score/percentage as a JSON number."""
    return float(round_half_up(value, 2))


def cents(value):
    """Whole cents, round half up."""
    return int(round_half_up(value, 0))


# ------------------------------------------------------------ classification


def classify(action, office):
    disturbance = D(action["disturbance_hectares"])
    if disturbance >= D(office["ea_threshold_disturbance_hectares"]):
        return "ENVIRONMENTAL_IMPACT_STATEMENT"
    if (
        disturbance >= D(office["ce_threshold_disturbance_hectares"])
        or action["extraordinary_circumstance_flag"] is True
        or action["in_critical_habitat"] is True
    ):
        return "ENVIRONMENTAL_ASSESSMENT"
    return "CATEGORICAL_EXCLUSION"


# ------------------------------------------------- extraordinary circumstances


def screen_derived(findings, office):
    threshold = office["ec_severity_trigger_threshold"]
    order = list(office["extraordinary_circumstance_codes"])
    triggered = set()
    max_severity = 0
    for finding in findings:
        if finding["present"]:
            if finding["severity"] > max_severity:
                max_severity = finding["severity"]
            if finding["severity"] >= threshold:
                triggered.add(finding["code"])
    triggered_codes = [code for code in order if code in triggered]
    return triggered_codes, max_severity


# ------------------------------------------------------- cumulative baseline


def cumulative_inclusion(entry_distance_km, office):
    if D(entry_distance_km) <= D(office["cumulative_radius_km"]):
        return "INCLUDED"
    return "EXCLUDED"


def cumulative_effect_score(entries):
    """Per-entry rounding, then summation, then the crowding multiplier."""
    subtotal = Decimal("0")
    count = 0
    for entry in entries:
        count += 1
        weight = Decimal("1.0") + min(
            FOOTPRINT_WEIGHT_CAP, D(entry["footprint_hectares"]) / FOOTPRINT_DIVISOR
        )
        contribution = round_half_up(
            D(entry["intensity_contribution"]) * weight * TEMPORAL_FACTOR[entry["temporal_scope"]],
            2,
        )
        subtotal += contribution
    crowding = Decimal("1.0") + CROWDING_STEP * max(0, count - CROWDING_FREE_ENTRIES)
    return round_half_up(subtotal * crowding, 2)


# -------------------------------------------------------- resource analysis


def area_tier_adder(hectares):
    value = D(hectares)
    if value == 0:
        return Decimal("0.0")
    if value <= 5:
        return Decimal("2.0")
    if value <= 25:
        return Decimal("4.0")
    if value <= 100:
        return Decimal("7.0")
    return Decimal("11.0")


def significance_scores(analysis, office, cumulative):
    base = D(office["intensity_weight"]) * D(analysis["intensity_score"]) + D(
        office["context_weight"]
    ) * D(analysis["context_sensitivity_score"])
    adder = area_tier_adder(analysis["affected_area_hectares"])
    uplift = CUMULATIVE_UPLIFT_RATE * max(Decimal("0.0"), D(cumulative) - CUMULATIVE_UPLIFT_FLOOR)
    direct = min(SCORE_CEILING, base + adder + uplift)
    unmitigated = round_half_up(direct, 2)
    mitigated = round_half_up(
        max(Decimal("0.0"), direct - D(analysis["mitigation_reduction_points"])), 2
    )
    return unmitigated, mitigated


def determination(score, office):
    if D(score) >= D(office["significance_threshold"]):
        return "SIGNIFICANT"
    return "NOT_SIGNIFICANT"


# ------------------------------------------------------------- alternatives


def feasibility_score(alternative_codes, statement, estimated_cost_cents, reference_cost_cents):
    goal_codes = list(statement["goal_codes"])
    matched = sum(1 for code in alternative_codes if code in goal_codes)
    alignment_ratio = D(matched) / D(len(goal_codes)) if goal_codes else Decimal("0")
    reference = D(reference_cost_cents)
    overrun = max(Decimal("0"), D(estimated_cost_cents) - reference) / reference
    cost_factor = max(Decimal("0"), Decimal("1.0") - overrun)
    return round_half_up(
        Decimal("100.0") * (ALIGNMENT_WEIGHT * alignment_ratio + COST_WEIGHT * cost_factor), 2
    )


# ------------------------------------------------------------ consultations


def required_consultation_types(action):
    required = set()
    if action["in_critical_habitat"]:
        required.add("ESA_SECTION_7")
    if action["affects_historic_property"] or action["tribal_interest"]:
        required.add("NHPA_SECTION_106")
    if action["floodplain_or_wetland"]:
        required.add("CWA_SECTION_404")
    return required


def occupied_interval(consultation, agency):
    start = db.parse_dt(consultation["requested_start_at"])
    end = db.add_days(db.parse_dt(consultation["statutory_due_at"]), agency["handoff_buffer_days"])
    return start, end


# --------------------------------------------------------------- mitigation


def lifecycle_obligation_cents(commitment, office):
    monitoring_raw = (
        D(commitment["monitoring_years"])
        * D(commitment["annual_monitoring_cost_cents"])
        * D(office["monitoring_escalation_factor"])
    )
    return int(commitment["cost_estimate_cents"]) + cents(monitoring_raw)


def fee_rate(credit_points):
    points = D(credit_points)
    if points >= FEE_TIER_HIGH_POINTS:
        return FEE_RATE_HIGH
    if points >= FEE_TIER_MID_POINTS:
        return FEE_RATE_MID
    return FEE_RATE_LOW


def decision_fiscals(binding_commitments, office, max_unmitigated_score):
    """The pinned forward pass of PRD 3.9 -- never iterated to a fixed point."""
    committed = sum(int(c["cost_estimate_cents"]) for c in binding_commitments)
    base = sum(lifecycle_obligation_cents(c, office) for c in binding_commitments)

    declared_points = sum((D(c["reduction_points"]) for c in binding_commitments), Decimal("0"))
    per_point = D(office["cost_per_reduction_point_cents"])
    if per_point == 0:
        capacity_points = Decimal("Infinity")
    else:
        capacity_points = D(base) / per_point
    credit_points = round_half_up(
        min(declared_points, capacity_points, D(office["max_mitigated_reduction_points"])), 2
    )

    rate = fee_rate(credit_points)
    contingency = cents(D(base) * rate)
    binding = base + contingency
    mitigated_max = round_half_up(
        max(Decimal("0.00"), D(max_unmitigated_score) - credit_points), 2
    )
    return {
        "committed_obligation_cents": int(committed),
        "base_obligation_cents": int(base),
        "credit_points": float(credit_points),
        "contingency_fee_cents": int(contingency),
        "binding_obligation_cents": int(binding),
        "mitigated_max_score": float(mitigated_max),
    }
