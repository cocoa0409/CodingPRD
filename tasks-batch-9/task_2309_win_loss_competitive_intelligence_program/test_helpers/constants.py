"""
Pinned constants and pure calculators for the Win-Loss Intelligence API.

Every literal here is transcribed from PRD.md. The calculators reproduce the
PRD's rounding discipline exactly: "All rounding in this system is round half
up, applied at the exact points named below and nowhere else, because several
formulas round intermediate values before combining them and would produce
different outputs under a different rounding order." (PRD 2.7)
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up(value, places: int) -> Decimal:
    """Round a value half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def money(value) -> Decimal:
    """Round to the 2 decimal places every monetary field carries."""
    return round_half_up(value, 2)


def ratio(value) -> Decimal:
    """Round to the 4 decimal places every ratio/score field carries."""
    return round_half_up(value, 4)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_RESEARCH_ANALYST = "ResearchAnalyst"
ROLE_LEGAL_REVIEWER = "LegalReviewer"
ROLE_ENABLEMENT_MANAGER = "EnablementManager"
ROLE_PRODUCT_MANAGER = "ProductManager"
ROLE_SALES_REP = "SalesRep"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_RESEARCH_ANALYST,
    ROLE_LEGAL_REVIEWER,
    ROLE_ENABLEMENT_MANAGER,
    ROLE_PRODUCT_MANAGER,
    ROLE_SALES_REP,
)

# ---------------------------------------------------------------------------
# Enumerations (PRD 3.x)
# ---------------------------------------------------------------------------

PROGRAM_STATUSES = ("DRAFT", "ACTIVE", "CLOSING", "CLOSED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
INDEPENDENCE_MODES = ("STRICT", "ADVISORY")

COMPETITOR_TIERS = ("PRIMARY", "SECONDARY", "EMERGING")
COMPETITOR_STATUSES = ("ACTIVE", "ARCHIVED")

DEAL_OUTCOMES = ("WON", "LOST", "NO_DECISION")
DEAL_SEGMENTS = ("ENTERPRISE", "MIDMARKET", "SMB")
DEAL_RESEARCH_STATUSES = (
    "NOT_SELECTED",
    "SELECTED",
    "DECLINED",
    "INTERVIEWED",
    "SYNTHESIZED",
)
DEAL_ATTRIBUTION_STATUSES = ("UNATTRIBUTED", "PROVISIONAL", "RATIFIED")

EMPLOYMENT_TYPES = ("INTERNAL", "EXTERNAL_VENDOR")
ANALYST_STATUSES = ("ACTIVE", "INACTIVE")

TITLE_BANDS = ("ECONOMIC_BUYER", "CHAMPION", "PROCUREMENT", "END_USER")
INCENTIVE_ELIGIBILITIES = ("ELIGIBLE", "INELIGIBLE_PUBLIC_SECTOR", "INELIGIBLE_POLICY")
CONSENT_STATUSES = ("NOT_REQUESTED", "REQUESTED", "GRANTED", "REFUSED")

FRAME_STATUSES = ("DRAFT", "SEALED", "SUSPENDED", "CLOSED")
SELECTION_BASES = ("STRATIFIED_BY_SEGMENT", "VALUE_WEIGHTED")
STRATA = ("WON", "LOST", "NO_DECISION")

INTERVIEW_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
INCENTIVE_STATUSES = ("COMMITTED", "PAID", "FORFEITED", "RELEASED")

QUESTION_KEYS = (
    "EVALUATION_CRITERIA",
    "COMPETITOR_POSITIONING",
    "PRICING_PERCEPTION",
    "LOSS_REASON",
    "PRODUCT_GAP",
)

LOSS_REASON_STATUSES = ("ACTIVE", "DEPRECATED")
ATTRIBUTION_STATUSES = ("PROVISIONAL", "RATIFIED", "SUPERSEDED")
TREND_BASES = ("RATIFIED_ONLY", "INCLUDE_PROVISIONAL")

BATTLECARD_STATUSES = ("DRAFT", "LEGAL_REVIEW", "APPROVED", "PUBLISHED", "WITHDRAWN")
CLAIM_TYPES = ("PRICING", "FEATURE", "PERFORMANCE", "REFERENCE")
CLAIM_LEGAL_STATUSES = ("PENDING", "APPROVED", "CONDITIONAL", "REJECTED")
LEGAL_DECISIONS = ("APPROVE", "CONDITIONAL", "REJECT")
SUBSTANTIATION_LEVELS = ("UNSUBSTANTIATED", "ANECDOTAL", "CORROBORATED")
RISK_CLASSES = ("LOW", "MEDIUM", "HIGH")

ASSIGNMENT_STATUSES = ("ASSIGNED", "FAILED", "TRAINED", "EXPIRED")

PRODUCT_GAP_STATUSES = ("NEW", "TRIAGED", "ACCEPTED", "DECLINED", "PROMOTED")
TRIAGE_DECISIONS = ("ACCEPT", "NEEDS_EVIDENCE", "DECLINE")
ROADMAP_BANDS = ("P0", "P1", "P2", "P3")

# ---------------------------------------------------------------------------
# Program defaults (PRD 3.1)
# ---------------------------------------------------------------------------

DEFAULT_REQUIRED_QUESTION_KEYS = [
    "EVALUATION_CRITERIA",
    "COMPETITOR_POSITIONING",
    "PRICING_PERCEPTION",
]
DEFAULT_MAX_OPEN_INTERVIEWS_PER_ANALYST = 3
DEFAULT_INDEPENDENCE_MODE = "STRICT"
DEFAULT_INCENTIVE_ELIGIBILITY = "ELIGIBLE"

# ---------------------------------------------------------------------------
# Program posture (PRD 2.9)
# ---------------------------------------------------------------------------

POSTURE_RESTRICTED_AT = Decimal("0.8500")
POSTURE_FROZEN_AT = Decimal("1.0000")
POSTURE_STATUS_FLOOR = {
    "DRAFT": "OPEN",
    "ACTIVE": "OPEN",
    "CLOSING": "RESTRICTED",
    "CLOSED": "FROZEN",
}
POSTURE_STRICTNESS = {"OPEN": 0, "RESTRICTED": 1, "FROZEN": 2}

# ---------------------------------------------------------------------------
# Sample selection scoring (PRD 3.3)
# ---------------------------------------------------------------------------

VALUE_NORMALIZER_USD = Decimal("250000")
RECENCY_HORIZON_DAYS = 180
COMPETITOR_TIER_WEIGHT = {
    "PRIMARY": Decimal("0.30"),
    "SECONDARY": Decimal("0.20"),
    "EMERGING": Decimal("0.10"),
    "NONE": Decimal("0.00"),
}
STRATIFIED_VALUE_WEIGHT = Decimal("0.40")
STRATIFIED_RECENCY_WEIGHT = Decimal("0.40")
VALUE_WEIGHTED_VALUE_WEIGHT = Decimal("0.65")
VALUE_WEIGHTED_RECENCY_WEIGHT = Decimal("0.15")
ENTERPRISE_VALUE_MULTIPLIER = Decimal("1.25")
SEGMENT_RANK = {"ENTERPRISE": 1, "MIDMARKET": 2, "SMB": 3}

# ---------------------------------------------------------------------------
# Buyer incentive (PRD 3.5)
# ---------------------------------------------------------------------------

INCENTIVE_BASE_USD = {
    "ECONOMIC_BUYER": Decimal("250.00"),
    "CHAMPION": Decimal("175.00"),
    "PROCUREMENT": Decimal("150.00"),
    "END_USER": Decimal("100.00"),
}
DURATION_EXTENDED_MIN = 75
DURATION_EXTENDED_FACTOR = Decimal("1.25")
DURATION_FULL_MIN = 45
DURATION_FULL_FACTOR = Decimal("1.00")
DURATION_PARTIAL_MIN = 25
DURATION_PARTIAL_FACTOR = Decimal("0.60")
DURATION_ZERO_FACTOR = Decimal("0.00")
EXTERNAL_VENDOR_UPLIFT = Decimal("1.10")

DEBRIEF_BUFFER_MINUTES = 15
NO_SHOW_GRACE_MINUTES = 15
COOLING_OFF_DAYS = 90
MAX_RESCHEDULES = 2

# ---------------------------------------------------------------------------
# Attribution (PRD 3.6)
# ---------------------------------------------------------------------------

WEIGHT_PRIMARY_MIN = Decimal("0.50")
WEIGHT_PRIMARY_MAX = Decimal("1.00")
CONFIDENCE_BASE = Decimal("0.40")
CONFIDENCE_PER_INTERVIEW = Decimal("0.20")
CONFIDENCE_FACTOR_CAP = Decimal("1.00")
MAX_TAXONOMY_DEPTH = 3
SEGMENT_ORDER = ("ENTERPRISE", "MIDMARKET", "SMB")

# ---------------------------------------------------------------------------
# Claim substantiation (PRD 3.7)
# ---------------------------------------------------------------------------

SOURCE_WEIGHT = {
    "COMPETITOR_POSITIONING": Decimal("1.00"),
    "PRICING_PERCEPTION": Decimal("0.90"),
    "EVALUATION_CRITERIA": Decimal("0.70"),
    "LOSS_REASON": Decimal("0.50"),
    "PRODUCT_GAP": Decimal("0.40"),
}
RATING_FACTOR_BASE = Decimal("0.60")
RATING_FACTOR_PER_POINT = Decimal("0.10")
EVIDENCE_RECENCY_DAYS = 90
FRESH_EVIDENCE_FACTOR = Decimal("1.00")
STALE_EVIDENCE_FACTOR = Decimal("0.75")

CORROBORATED_MIN = Decimal("2.00")
ANECDOTAL_MIN = Decimal("0.90")

CLAIM_TYPE_BASE_RISK = {
    "PRICING": 3,
    "PERFORMANCE": 3,
    "FEATURE": 2,
    "REFERENCE": 1,
}
LEVEL_RISK_OFFSET = {"UNSUBSTANTIATED": 1, "ANECDOTAL": 0, "CORROBORATED": -1}
RISK_CLASS_BY_POINTS = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}
RISK_POINTS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

# ---------------------------------------------------------------------------
# Battlecard risk index (PRD 3.7)
# ---------------------------------------------------------------------------

LEGAL_DISCOUNT_HIGH_AT = Decimal("2.50")
LEGAL_DISCOUNT_HIGH = Decimal("0.25")
LEGAL_DISCOUNT_MID_AT = Decimal("1.50")
LEGAL_DISCOUNT_MID = Decimal("0.10")
CONDITIONAL_SURCHARGE = Decimal("0.15")
RISK_INDEX_CEILING = Decimal("3.00")
PUBLISH_RISK_CEILING = Decimal("2.20")

# ---------------------------------------------------------------------------
# Enablement adoption (PRD 3.8)
# ---------------------------------------------------------------------------

QUIZ_PASS_SCORE = 80
QUIZ_SCORE_MIN = 0
QUIZ_SCORE_MAX = 100
ADOPTION_GATE = Decimal("0.6000")

# ---------------------------------------------------------------------------
# Product gap impact (PRD 3.9)
# ---------------------------------------------------------------------------

IMPACT_ACR_NORMALIZER = Decimal("500000")
IMPACT_ACR_WEIGHT = Decimal("40")
IMPACT_FREQ_WEIGHT = Decimal("4")
IMPACT_FREQ_CAP = 10
COMPETITOR_PRESSURE = {
    "PRIMARY": Decimal("1.30"),
    "SECONDARY": Decimal("1.10"),
    "EMERGING": Decimal("1.00"),
    "NONE": Decimal("1.00"),
}
BAND_P0_MIN = Decimal("70")
BAND_P1_MIN = Decimal("45")
BAND_P2_MIN = Decimal("20")

# ---------------------------------------------------------------------------
# Pure calculators
# ---------------------------------------------------------------------------

def duration_factor(minutes: int) -> Decimal:
    """PRD 3.5 duration ladder, evaluated from the top, first match winning."""
    if minutes >= DURATION_EXTENDED_MIN:
        return DURATION_EXTENDED_FACTOR
    if minutes >= DURATION_FULL_MIN:
        return DURATION_FULL_FACTOR
    if minutes >= DURATION_PARTIAL_MIN:
        return DURATION_PARTIAL_FACTOR
    return DURATION_ZERO_FACTOR


def incentive_amount(
    title_band: str,
    minutes: int,
    cap_usd,
    eligibility: str = "ELIGIBLE",
    employment_type: str = "INTERNAL",
) -> Decimal:
    """
    PRD 3.5 buyer-incentive amount. The external-vendor uplift multiplies the
    already-rounded gross, so rounding happens twice in that path.
    """
    if eligibility != "ELIGIBLE":
        return money("0.00")
    gross = money(INCENTIVE_BASE_USD[title_band] * duration_factor(minutes))
    if employment_type == "EXTERNAL_VENDOR":
        gross = money(gross * EXTERNAL_VENDOR_UPLIFT)
    return min(gross, money(cap_usd))


def utilization(committed, paid, budget) -> Decimal:
    """PRD 2.9 budget utilization, 4dp, taken as 1.0000 when the budget is zero."""
    budget = Decimal(str(budget))
    if budget == 0:
        return Decimal("1.0000")
    return ratio((Decimal(str(committed)) + Decimal(str(paid))) / budget)


def posture_from(committed, paid, budget, program_status: str) -> str:
    """PRD 2.9 posture: stricter of the utilization ladder and the status floor."""
    util = utilization(committed, paid, budget)
    if util >= POSTURE_FROZEN_AT:
        derived = "FROZEN"
    elif util >= POSTURE_RESTRICTED_AT:
        derived = "RESTRICTED"
    else:
        derived = "OPEN"
    floor = POSTURE_STATUS_FLOOR[program_status]
    return derived if POSTURE_STRICTNESS[derived] >= POSTURE_STRICTNESS[floor] else floor


def value_term(acr_usd) -> Decimal:
    """PRD 3.3 value term: acr / 250000, capped at 1.0000, 4dp."""
    return min(ratio(Decimal(str(acr_usd)) / VALUE_NORMALIZER_USD), Decimal("1.0000"))


def recency_term(whole_days_since_close: int) -> Decimal:
    """PRD 3.3 recency term: (180 - days) / 180, floored at 0.0000, 4dp."""
    raw = (Decimal(RECENCY_HORIZON_DAYS) - Decimal(whole_days_since_close)) / Decimal(
        RECENCY_HORIZON_DAYS
    )
    return max(ratio(raw), Decimal("0.0000"))


def selection_rank_score(
    acr_usd,
    whole_days_since_close: int,
    competitor_tier: Optional[str],
    segment: str,
    selection_basis: str,
) -> Decimal:
    """PRD 3.3 selection score under either declared basis."""
    v = value_term(acr_usd)
    r = recency_term(whole_days_since_close)
    c = COMPETITOR_TIER_WEIGHT[competitor_tier or "NONE"]
    if selection_basis == "STRATIFIED_BY_SEGMENT":
        return ratio(STRATIFIED_VALUE_WEIGHT * v + STRATIFIED_RECENCY_WEIGHT * r + c)
    raw = VALUE_WEIGHTED_VALUE_WEIGHT * v + VALUE_WEIGHTED_RECENCY_WEIGHT * r + c
    if segment == "ENTERPRISE":
        raw = raw * ENTERPRISE_VALUE_MULTIPLIER
    return ratio(raw)


def rating_factor(rating: Optional[int]) -> Decimal:
    """PRD 3.7 rating factor: 1.00 when null, else 0.60 + 0.10 per rating point."""
    if rating is None:
        return Decimal("1.00")
    return RATING_FACTOR_BASE + RATING_FACTOR_PER_POINT * Decimal(rating)


def evidence_item_score(
    question_key: str, rating: Optional[int], whole_days_old: int
) -> Decimal:
    """PRD 3.7: one evidence contribution, rounded to 2dp before any addition."""
    recency = (
        FRESH_EVIDENCE_FACTOR
        if whole_days_old <= EVIDENCE_RECENCY_DAYS
        else STALE_EVIDENCE_FACTOR
    )
    return money(SOURCE_WEIGHT[question_key] * rating_factor(rating) * recency)


def substantiation_score(items: Sequence[Decimal]) -> Decimal:
    """PRD 3.7 round-then-sum: the sum of already-rounded items, rounded again."""
    total = sum(items, Decimal("0"))
    return money(total)


def substantiation_level(score) -> str:
    """PRD 3.7 level ladder with inclusive boundaries."""
    score = Decimal(str(score))
    if score >= CORROBORATED_MIN:
        return "CORROBORATED"
    if score >= ANECDOTAL_MIN:
        return "ANECDOTAL"
    return "UNSUBSTANTIATED"


def risk_class(claim_type: str, level: str) -> str:
    """PRD 3.7 risk class: base points, level offset, clamped into 1..3."""
    points = CLAIM_TYPE_BASE_RISK[claim_type] + LEVEL_RISK_OFFSET[level]
    points = max(1, min(3, points))
    return RISK_CLASS_BY_POINTS[points]


def risk_index_pre(risk_classes: Sequence[str]) -> Decimal:
    """PRD 3.7 stage two: average risk of the non-rejected input set, 2dp."""
    if not risk_classes:
        return money("0.00")
    total = sum(RISK_POINTS[rc] for rc in risk_classes)
    return money(Decimal(total) / Decimal(len(risk_classes)))


def risk_index_final(risk_classes: Sequence[str], legal_statuses: Sequence[str]) -> Decimal:
    """PRD 3.7 stages three through five, in their pinned order."""
    if not risk_classes:
        return money("0.00")
    pre = risk_index_pre(risk_classes)
    if pre >= LEGAL_DISCOUNT_HIGH_AT:
        discount = LEGAL_DISCOUNT_HIGH
    elif pre >= LEGAL_DISCOUNT_MID_AT:
        discount = LEGAL_DISCOUNT_MID
    else:
        discount = Decimal("0.00")
    cleared = sum(1 for s in legal_statuses if s in ("APPROVED", "CONDITIONAL"))
    scale = ratio(Decimal(cleared) / Decimal(len(risk_classes)))
    after_discount = money(pre * (Decimal("1") - ratio(discount * scale)))
    conditional = sum(1 for s in legal_statuses if s == "CONDITIONAL")
    result = after_discount + CONDITIONAL_SURCHARGE * Decimal(conditional)
    return money(min(result, RISK_INDEX_CEILING))


def confidence_score(weight_primary, interview_coverage_count: int) -> Decimal:
    """PRD 3.6 confidence: weight_primary times the coverage factor, 2dp."""
    factor = min(
        CONFIDENCE_BASE + CONFIDENCE_PER_INTERVIEW * Decimal(interview_coverage_count),
        CONFIDENCE_FACTOR_CAP,
    )
    return money(Decimal(str(weight_primary)) * factor)


def adoption_rate(trained_count: int, assigned_count: int) -> Decimal:
    """PRD 3.8 adoption rate, 4dp, or 0.0000 when the denominator is zero."""
    if assigned_count == 0:
        return Decimal("0.0000")
    return ratio(Decimal(trained_count) / Decimal(assigned_count))


def coverage_ratio(selected_total: int, quota_total: int) -> Decimal:
    """PRD 3.3 coverage ratio, 4dp, or 0.0000 when the total quota is zero."""
    if quota_total == 0:
        return Decimal("0.0000")
    return ratio(Decimal(selected_total) / Decimal(quota_total))


def impact_score(
    affected_acr_usd, linked_deal_count: int, competitor_tier: Optional[str]
) -> Decimal:
    """PRD 3.9 impact score: revenue component plus frequency component, scaled."""
    capped = min(
        ratio(Decimal(str(affected_acr_usd)) / IMPACT_ACR_NORMALIZER), Decimal("1.0000")
    )
    revenue_component = money(capped * IMPACT_ACR_WEIGHT)
    frequency_component = Decimal(min(linked_deal_count, IMPACT_FREQ_CAP)) * IMPACT_FREQ_WEIGHT
    pressure = COMPETITOR_PRESSURE[competitor_tier or "NONE"]
    return money((revenue_component + frequency_component) * pressure)


def roadmap_priority_band(score) -> str:
    """PRD 3.9 band ladder with inclusive boundaries."""
    score = Decimal(str(score))
    if score >= BAND_P0_MIN:
        return "P0"
    if score >= BAND_P1_MIN:
        return "P1"
    if score >= BAND_P2_MIN:
        return "P2"
    return "P3"


def win_rate_vs(won: int, decided: int) -> Optional[Decimal]:
    """PRD 3.2 win rate, 4dp, null when the denominator is zero."""
    if decided == 0:
        return None
    return ratio(Decimal(won) / Decimal(decided))
