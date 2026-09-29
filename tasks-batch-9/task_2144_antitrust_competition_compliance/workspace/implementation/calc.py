"""Calculation rules (scaffold section 1.3 / PRD section 3)."""
from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------ constants
INTERACTION_POINT_WEIGHT = Decimal("3")
INTERACTION_COMPONENT_CAP = Decimal("30")
OVERLAP_WEIGHT = Decimal("0.20")
ESCALATED_CONTACT_WEIGHT = Decimal("5")
FLAGGED_ATTENDANCE_WEIGHT = Decimal("3")
DOCUMENT_VIOLATION_WEIGHT = Decimal("2")
INCIDENT_LOAD_CAP = Decimal("25")

HSR_SIZE_OF_TRANSACTION_THRESHOLD_CENTS = 12000000000
HSR_SIZE_OF_TRANSACTION_UPPER_CENTS = 48000000000
HSR_SIZE_OF_PERSON_LARGE_CENTS = 48000000000
HSR_SIZE_OF_PERSON_SMALL_CENTS = 4800000000
HSR_WAITING_PERIOD_DAYS = 30

CONTACT_BASE_POINTS = Decimal("4")
PRICING_TOPIC_POINTS = Decimal("6")
RAW_POINTS_CAP = Decimal("20")
TAG_POINTS_CAP = Decimal("5")
CHANNEL_POINTS = {
    "IN_PERSON_UNSTRUCTURED": Decimal("3"),
    "TRADE_SHOW": Decimal("2"),
    "PHONE": Decimal("1"),
    "EMAIL": Decimal("1"),
    "WRITTEN_FORMAL": Decimal("0"),
}
TAG_POINTS = {
    "CAPACITY": Decimal("2"),
    "BID": Decimal("2"),
    "CUSTOMER_ALLOCATION": Decimal("3"),
    "TERRITORY": Decimal("3"),
    "STANDARDS": Decimal("0"),
    "BENCHMARKING": Decimal("1"),
}
ROLE_POINTS = {
    "SALES": Decimal("2"),
    "PRICING": Decimal("3"),
    "LEGAL": Decimal("0"),
    "OTHER": Decimal("1"),
}
BAND_MULTIPLIER = {
    "LOW": Decimal("1.0"),
    "MODERATE": Decimal("1.25"),
    "HIGH": Decimal("1.5"),
    "SEVERE": Decimal("2.0"),
}
ESCALATION_SURCHARGE_MULTIPLIER = Decimal("2.0")

RESTRICTED_EXPOSURE_THRESHOLD = Decimal("40")
FROZEN_EXPOSURE_THRESHOLD = Decimal("80")

REVIEW_BASE_MINUTES = 30
TIER_MINUTES = {"TIER_1_LOW": 0, "TIER_2_MEDIUM": 20, "TIER_3_HIGH": 45}
DENSITY_STEP_MINUTES = 5
DENSITY_STEP_PCT = Decimal("25")

VERDICT_POINTS = {"CLEAN": Decimal("0"), "CONCERN": Decimal("5"), "VIOLATION": Decimal("12")}
FINDING_POINTS = {
    "PRICING_DISCUSSION": Decimal("8"),
    "CAPACITY_DISCUSSION": Decimal("6"),
    "CUSTOMER_ALLOCATION": Decimal("10"),
    "BID_COORDINATION": Decimal("10"),
    "MARKET_DATA_AGGREGATE": Decimal("1"),
    "NONE": Decimal("0"),
}
FINDING_POINTS_CAP = Decimal("15")

MARKER_VALIDITY_DAYS = 30
DURATION_STEP = Decimal("0.10")
DURATION_MULTIPLIER_CAP = Decimal("2.00")
REDUCTION_BY_RANK = {1: Decimal("100"), 2: Decimal("50"), 3: Decimal("30")}

COUNSEL_BRIEFING_BUFFER_MINUTES = 60
AGENDA_LEAD_HOURS = 48
HIGH_RISK_PHRASE_PENALTY = Decimal("2")

MEETING_TYPES = ["BOARD", "COMMITTEE", "STANDARDS", "SOCIAL"]
DRILL_TYPES = ["DAWN_RAID", "DOCUMENT_HOLD", "INTERVIEW"]
ROLE_CATEGORIES = ["SALES", "PRICING", "LEGAL", "OTHER"]
CONTACT_CHANNELS = list(CHANNEL_POINTS.keys())
TOPIC_TAGS = list(TAG_POINTS.keys())
FINDING_CODES = list(FINDING_POINTS.keys())
VERDICTS = list(VERDICT_POINTS.keys())
APPROVAL_TIERS = list(TIER_MINUTES.keys())
EXEMPTION_CODES = ["NONE", "ORDINARY_COURSE", "FOREIGN_ASSETS", "INVESTMENT_ONLY"]
VALUATION_VARIANTS = ["SIGNED_DEAL", "MARKET_VALUE"]
ASSESSMENT_VARIANTS = ["BASELINE", "INCIDENT_ADJUSTED"]
RISK_BANDS = ["LOW", "MODERATE", "HIGH", "SEVERE"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]


# ------------------------------------------------------------------- rounding
def d(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def r2(value):
    return d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r0(value):
    return int(d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numer, denom):
    numer = d(numer)
    denom = d(denom)
    if numer <= 0:
        return 0
    q = numer / denom
    whole = int(q)
    if d(whole) < q:
        whole += 1
    return whole


def num(value):
    """Serialise a Decimal points figure as a JSON number with 2dp semantics."""
    if value is None:
        return None
    return float(r2(value))


# ------------------------------------------------------- 1. market_risk_index
def share_component(market_share_bps):
    bps = int(market_share_bps)
    if bps < 1500:
        return Decimal("10")
    if bps < 3000:
        return Decimal("25")
    if bps < 5000:
        return Decimal("45")
    return Decimal("70")


def band_for_index(index):
    if index < Decimal("25"):
        return "LOW"
    if index < Decimal("50"):
        return "MODERATE"
    if index < Decimal("75"):
        return "HIGH"
    return "SEVERE"


def market_risk_index(unit, variant, escalated, flagged, violations):
    share = share_component(unit["market_share_bps"])
    interaction = min(
        INTERACTION_COMPONENT_CAP,
        d(unit["interaction_point_count"]) * INTERACTION_POINT_WEIGHT,
    )
    overlap = r2(d(unit["competitor_overlap_pct"]) * OVERLAP_WEIGHT)
    base = share + interaction + overlap
    if variant == "BASELINE":
        escalated = 0
        flagged = 0
        violations = 0
        incident_load = Decimal("0")
    else:
        incident_load = min(
            INCIDENT_LOAD_CAP,
            ESCALATED_CONTACT_WEIGHT * d(escalated)
            + FLAGGED_ATTENDANCE_WEIGHT * d(flagged)
            + DOCUMENT_VIOLATION_WEIGHT * d(violations),
        )
    index = min(Decimal("100.00"), r2(base + incident_load))
    return {
        "share_component": share,
        "interaction_component": interaction,
        "overlap_component": overlap,
        "incident_load": incident_load,
        "escalated_contact_count": escalated,
        "flagged_attendance_count": flagged,
        "document_violation_count": violations,
        "market_risk_index": index,
        "risk_band": band_for_index(index),
    }


# -------------------------------------------------- 2. hsr_size_of_transaction
def hsr_size_of_transaction(txn, variant):
    if variant == "SIGNED_DEAL":
        size = int(txn["deal_value_cents"]) + int(txn["assumed_liabilities_cents"])
    else:
        size = int(txn["market_valuation_cents"]) + int(txn["assumed_liabilities_cents"])

    if txn.get("exemption_code", "NONE") != "NONE":
        determination, required = "EXEMPT", False
    elif size < HSR_SIZE_OF_TRANSACTION_THRESHOLD_CENTS:
        determination, required = "BELOW_THRESHOLD", False
    elif size >= HSR_SIZE_OF_TRANSACTION_UPPER_CENTS:
        determination, required = "FILING_REQUIRED", True
    else:
        large = max(int(txn["acquirer_total_assets_cents"]), int(txn["target_total_assets_cents"]))
        small = min(int(txn["acquirer_total_assets_cents"]), int(txn["target_total_assets_cents"]))
        if large >= HSR_SIZE_OF_PERSON_LARGE_CENTS and small >= HSR_SIZE_OF_PERSON_SMALL_CENTS:
            determination, required = "FILING_REQUIRED", True
        else:
            determination, required = "SIZE_OF_PERSON_NOT_MET", False
    return size, determination, required


# ---------------------------------------------------- 3. contact_exposure_points
def contact_exposure_points(channel, tags, pricing_topic, role_category, risk_band):
    channel_points = CHANNEL_POINTS[channel]
    tag_points = min(TAG_POINTS_CAP, sum((TAG_POINTS[t] for t in tags), Decimal("0")))
    role_points = ROLE_POINTS[role_category]
    raw = (
        CONTACT_BASE_POINTS
        + (PRICING_TOPIC_POINTS if pricing_topic else Decimal("0"))
        + channel_points
        + tag_points
        + role_points
    )
    capped_raw = min(RAW_POINTS_CAP, raw)
    multiplier = BAND_MULTIPLIER[risk_band]
    return r2(capped_raw * multiplier), multiplier


# --------------------------------------------- 6. participation_review_load_minutes
def participation_review_load_minutes(association):
    steps = ceil_div(d(association["competitor_density_pct"]), DENSITY_STEP_PCT)
    base_minutes = (
        REVIEW_BASE_MINUTES
        + TIER_MINUTES[association["approval_tier"]]
        + DENSITY_STEP_MINUTES * steps
    )
    if base_minutes < 60:
        escalation = 0
    elif base_minutes < 100:
        escalation = 15
    else:
        escalation = 30
    return base_minutes + escalation


# ------------------------------------------- 7. minutes_review_exposure_points
def minutes_review_exposure_points(verdict, findings, risk_band):
    finding_points = min(
        FINDING_POINTS_CAP, sum((FINDING_POINTS[f] for f in findings), Decimal("0"))
    )
    return r2((VERDICT_POINTS[verdict] + finding_points) * BAND_MULTIPLIER[risk_band])


# ------------------------------------------------- 9. leniency_penalty_estimate
def leniency_penalty_estimate(affected_years, gravity_pct, priority_rank):
    if gravity_pct is None:
        return None
    ordered = sorted(affected_years, key=lambda y: y["year"])
    base_penalty = 0
    for entry in ordered:
        base_penalty += r0(d(entry["affected_commerce_cents"]) * d(gravity_pct) / Decimal("100"))
    duration_multiplier = min(
        DURATION_MULTIPLIER_CAP, Decimal("1") + DURATION_STEP * d(len(affected_years) - 1)
    )
    reduction = REDUCTION_BY_RANK.get(priority_rank, Decimal("0")) if priority_rank else Decimal("0")
    return r0(d(base_penalty) * duration_multiplier * (Decimal("100") - reduction) / Decimal("100"))


# ------------------------------------------------- 13. document_guideline_score
def document_guideline_score(sample_size, violation_count, high_risk_phrase_count):
    ratio = r2(d(violation_count) * Decimal("100") / d(sample_size))
    score = r2(Decimal("100") - ratio - HIGH_RISK_PHRASE_PENALTY * d(high_risk_phrase_count))
    return max(Decimal("0.00"), score)
