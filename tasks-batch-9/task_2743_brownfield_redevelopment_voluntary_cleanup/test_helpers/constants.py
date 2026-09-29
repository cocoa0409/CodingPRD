"""
Every literal the PRD pins, plus the rounding helpers the arithmetic depends on.

The PRD says all money is carried as an integer number of cents and that rounding is
"round half up at the pinned step". Python's own ``round`` is banker's rounding and
would disagree with the specification on exact halves, so every helper here goes
through ``decimal.Decimal`` with ``ROUND_HALF_UP``.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence

# ─── Envelope, paths and the logical clock ────────────────────────────────────

CLOCK_PATH = "/_clock/set_current_utc"

# "The clock starts at exactly 2026-08-01T00:00:00Z."
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

REQUEST_ID_PREFIX = "req_"
TIMESTAMP_FRACTIONAL_DIGITS = 3

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")
REQUEST_META_FIELDS = ("api_request_id", "api_request_timestamp")

# ─── Enumerations ─────────────────────────────────────────────────────────────

PARTY_TYPES = ("REDEVELOPER", "CONSULTANT", "INSURER")

INTENDED_REUSES = ("RESIDENTIAL", "RECREATIONAL", "COMMERCIAL", "INDUSTRIAL")
ACQUISITION_STATUSES = ("UNDER_CONTRACT", "ACQUIRED")
DELINEATION_STATUSES = ("NONE", "SCREENED", "DELINEATED")
CLEANUP_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")

PHASE_TYPES = ("PHASE_I", "PHASE_II", "SUPPLEMENTAL")
PHASE_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
    "REJECTED",
)
DELINEATION_CONFIDENCES = ("SCREENING", "PARTIAL", "FULL")

MEDIA_VALUES = ("SOIL", "GROUNDWATER", "SOIL_VAPOR")

GOAL_BASES = ("UNRESTRICTED", "RESTRICTED")
CONTROL_TYPES = (
    "VAPOR_MITIGATION",
    "ENGINEERED_CAP",
    "GW_USE_RESTRICTION",
    "DEED_RESTRICTION",
)
ENGINEERING_CONTROL_TYPES = ("VAPOR_MITIGATION", "ENGINEERED_CAP")
INSTITUTIONAL_CONTROL_TYPES = ("GW_USE_RESTRICTION", "DEED_RESTRICTION")
CONTROL_CLASSES = ("ENGINEERING", "INSTITUTIONAL")
CONTROL_STATUSES = ("PROPOSED", "APPROVED", "OPERATING", "IMPAIRED", "DECOMMISSIONED")

ATTAINMENT_STATUSES = ("NOT_ATTAINED", "ATTAINED")

INQUIRY_STATES = ("AAI_PENDING", "AAI_COMPLETE", "AAI_STALE", "AAI_DEFICIENT")
OBLIGATION_STATES = ("OBLIGATIONS_NONE", "CURRENT", "AT_RISK", "LAPSED")
BFPP_STATUSES = ("NOT_ESTABLISHED", "ESTABLISHED", "FORFEITED")

OBLIGATION_CATEGORIES = (
    "REASONABLE_STEPS",
    "LAND_USE_RESTRICTION_COMPLIANCE",
    "ACCESS_AND_COOPERATION",
    "INSTITUTIONAL_CONTROL_MAINTENANCE",
    "NOTIFICATION",
)
OBLIGATION_STATUSES = ("CURRENT", "AT_RISK", "SATISFIED", "LAPSED")

PROGRAM_TRACKS = ("UNRESTRICTED_CLOSURE", "RESTRICTED_CLOSURE")
ENROLLMENT_STATUSES = (
    "APPLIED",
    "ELIGIBILITY_REVIEW",
    "ENROLLED",
    "REMEDY_APPROVED",
    "IMPLEMENTATION",
    "COMPLETION_REVIEW",
    "CLOSED",
    "REJECTED",
    "WITHDRAWN",
)

PLAN_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_TECHNICAL_REVIEW",
    "PUBLIC_COMMENT",
    "REVISION_REQUESTED",
    "APPROVED",
    "WITHDRAWN",
)
TECHNICAL_REVIEW_STATES = ("NOT_STARTED", "PASSED")
PUBLIC_COMMENT_STATES = ("NOT_STARTED", "OPEN", "CLOSED")

COST_CATEGORIES = (
    "EXCAVATION_DISPOSAL",
    "GW_TREATMENT",
    "VAPOR_MITIGATION",
    "MONITORING",
    "OVERSIGHT",
)

POLICY_STATUSES = ("QUOTED", "BOUND", "SUPERSEDED", "CANCELLED")

FUNDING_KINDS = ("GRANT", "TAX_CREDIT")
AWARD_STATUSES = ("APPLIED", "AWARDED", "DENIED", "RESCINDED")
ELIGIBILITY_DOCUMENTS = (
    "SITE_CONTROL_EVIDENCE",
    "BFPP_CERTIFICATION",
    "PHASE_II_REPORT",
    "COST_ESTIMATE",
    "MATCH_COMMITMENT",
)
GRANT_REQUIRED_DOCUMENTS = (
    "SITE_CONTROL_EVIDENCE",
    "PHASE_II_REPORT",
    "COST_ESTIMATE",
    "MATCH_COMMITMENT",
)
TAX_CREDIT_REQUIRED_DOCUMENTS = (
    "BFPP_CERTIFICATION",
    "PHASE_II_REPORT",
    "COST_ESTIMATE",
)

LETTER_SCOPES = ("UNRESTRICTED", "RESTRICTED_WITH_CONTROLS")
LETTER_STATUSES = ("DRAFT", "ISSUED", "ACCEPTED_BY_LENDER", "REVOKED")
REVOCATION_REASONS = ("BFPP_FORFEITED", "CONTROL_FAILURE")

EVENT_TYPES = ("SAMPLING", "CONTROL_INSPECTION")
EVENT_STATUSES = ("SCHEDULED", "REPORTED")
RESULT_STATUSES = ("PENDING", "COMPLIANT", "EXCEEDANCE")
CONTROL_CONDITIONS = ("PASS", "FAIL")

# ─── Risk-based cleanup goal ──────────────────────────────────────────────────

SCENARIO_MULTIPLIER = {
    "RESIDENTIAL": Decimal("1.0"),
    "RECREATIONAL": Decimal("2.5"),
    "COMMERCIAL": Decimal("3.5"),
    "INDUSTRIAL": Decimal("8.0"),
}
CONTROL_CREDIT = {
    "VAPOR_MITIGATION": Decimal("10.0"),
    "ENGINEERED_CAP": Decimal("4.0"),
    "GW_USE_RESTRICTION": Decimal("6.0"),
    "DEED_RESTRICTION": Decimal("1.0"),
}
MEDIA_ATTENUATION_DIVISOR = {
    "SOIL": Decimal("1.0"),
    "GROUNDWATER": Decimal("1.0"),
    "SOIL_VAPOR": Decimal("0.03"),
}
CUMULATIVE_RISK_BUDGET_UGL = Decimal("500.0")
PRACTICAL_QUANT_FLOOR_UGL = Decimal("0.50")

# ─── Remediation cost estimate ────────────────────────────────────────────────

MEDIA_FACTOR = {
    "SOIL": Decimal("1.00"),
    "GROUNDWATER": Decimal("1.35"),
    "SOIL_VAPOR": Decimal("1.15"),
}
ESCALATION_RATE_PER_YEAR = Decimal("0.042")
CONTINGENCY_TIER = {
    "SCREENING": Decimal("0.35"),
    "PARTIAL": Decimal("0.20"),
    "FULL": Decimal("0.10"),
}
CONTINGENCY_EXCEEDANCE_ADDER = Decimal("0.05")
CONTINGENCY_EXCEEDANCE_THRESHOLD = Decimal("10.0")
CONTINGENCY_UNDERWRITING_FLOOR = Decimal("0.25")
UNDERWRITING_ESCALATION_YEARS = 5
OVERSIGHT_RATE = Decimal("0.065")
OVERSIGHT_CAP_CENTS = 4000000

# ─── Cost-cap premium ─────────────────────────────────────────────────────────

ATTACHMENT_FACTOR = Decimal("1.10")
LIMIT_SHARE_OF_ESTIMATE = Decimal("0.30")
LIMIT_ROUNDING_STEP_CENTS = 10000000
RATE_TIER_LOW_RATIO = Decimal("0.35")
RATE_TIER_MID_RATIO = Decimal("0.60")
RATE_LOW = Decimal("0.070")
RATE_MID = Decimal("0.055")
RATE_HIGH = Decimal("0.045")
BROKER_FEE_RATE = Decimal("0.03")
MIN_PREMIUM_CENTS = 2500000
MIN_LIMIT_CENTS = 25000000
BIND_ATTACHMENT_MULTIPLIER = Decimal("1.05")

# ─── BFPP compliance ──────────────────────────────────────────────────────────

OBLIGATION_WEIGHTS = {
    "REASONABLE_STEPS": 5,
    "LAND_USE_RESTRICTION_COMPLIANCE": 5,
    "INSTITUTIONAL_CONTROL_MAINTENANCE": 4,
    "ACCESS_AND_COOPERATION": 3,
    "NOTIFICATION": 3,
}
DEFENCE_CRITICAL_CATEGORIES = ("REASONABLE_STEPS", "LAND_USE_RESTRICTION_COMPLIANCE")
COMPLIANCE_THRESHOLD = Decimal("0.85")
AT_RISK_GRACE_DAYS = 30
AAI_LOOKBACK_DAYS = 180
AAI_VALIDITY_DAYS = 365

# ─── Attainment ───────────────────────────────────────────────────────────────

ATTAINMENT_EVENTS_REQUIRED = 4

# ─── Controls ─────────────────────────────────────────────────────────────────

CONTROL_CHANGEOVER_BUFFER_DAYS = 30
CONTROL_INSPECTION_INTERVAL_MIN = 30
CONTROL_INSPECTION_INTERVAL_MAX = 730

# ─── Field bounds the PRD states ──────────────────────────────────────────────

LEGAL_NAME_MAX = 160
SITE_NAME_MAX = 160
COUNTY_CODE_MAX = 16
LAB_NAME_MAX = 120
CERTIFICATION_CODE_MAX = 32
SUB_AREA_CODE_MAX = 32
APPLICANT_STATEMENT_MAX = 600
REMEDY_NARRATIVE_MAX = 600
OBLIGATION_DESCRIPTION_MAX = 400
POLICY_REFERENCE_MAX = 64
PROGRAM_CODE_MAX = 48
MONITORING_PERIOD_CODE_MAX = 16
CONTAMINANT_CODE_MAX = 24
COST_LINES_MIN = 1
COST_LINES_MAX = 12
YEARS_TO_CONSTRUCTION_MIN = 0
YEARS_TO_CONSTRUCTION_MAX = 10
TERM_YEARS_MIN = 1
TERM_YEARS_MAX = 10
PROGRAM_PRIORITY_MIN = 1
PROGRAM_PRIORITY_MAX = 99
CONCURRENT_CAPACITY_MIN = 1
CONCURRENT_CAPACITY_MAX = 10
RECURRENCE_DAYS_MIN = 30

# The revision ceilings the two review loops enforce.
ASSESSMENT_REVISION_ROUND_CEILING = 3
PLAN_REVISION_ROUND_CEILING = 2

DECIMAL_TOLERANCE = Decimal("0.0000001")


# ─── Rounding ─────────────────────────────────────────────────────────────────


def round_half_up(value, places: int = 0) -> Decimal:
    """Round ``value`` half away from zero to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def round_half_up_cents(value) -> int:
    """Round to a whole number of cents, half up, as the PRD's money rule requires."""
    return int(round_half_up(value, 0))


def ceil_to_step(value: int, step: int) -> int:
    """Round ``value`` up to the next whole multiple of ``step``; a multiple stays put."""
    if value % step == 0:
        return int(value)
    return int((value // step + 1) * step)


# ─── Derivations the PRD states, re-expressed for expected-value assertions ───


def expected_line_cents(quantity, unit_cost_cents: int, media: str) -> int:
    """One cost line's whole-cent value: quantity x unit cost x the media factor."""
    return round_half_up_cents(
        Decimal(str(quantity)) * Decimal(unit_cost_cents) * MEDIA_FACTOR[media]
    )


def expected_direct_cost_cents(cost_lines: Sequence[dict]) -> int:
    """Sum of the already-rounded line values, in array order."""
    return sum(
        expected_line_cents(line["quantity"], line["unit_cost_cents"], line["media"])
        for line in cost_lines
    )


def expected_contingency_pct(
    delineation_confidence: str,
    max_exceedance_factor,
    underwriting: bool = False,
) -> Decimal:
    """The contingency rate for one basis phase, per basis."""
    base = CONTINGENCY_TIER[delineation_confidence]
    adder = (
        CONTINGENCY_EXCEEDANCE_ADDER
        if Decimal(str(max_exceedance_factor)) >= CONTINGENCY_EXCEEDANCE_THRESHOLD
        else Decimal("0.00")
    )
    total = base + adder
    if underwriting:
        return max(total, CONTINGENCY_UNDERWRITING_FLOOR)
    return total


def expected_cost_estimate(
    cost_lines: Sequence[dict],
    years_to_construction_start: int,
    delineation_confidence: str,
    max_exceedance_factor,
    underwriting: bool = False,
) -> dict:
    """
    Run the five-step estimate and return every figure it writes.

    ``underwriting`` swaps the two inputs the PRD says the two bases differ in: the
    escalation horizon becomes a fixed five years and the contingency rate is floored.
    """
    direct = expected_direct_cost_cents(cost_lines)
    years = UNDERWRITING_ESCALATION_YEARS if underwriting else years_to_construction_start
    escalation = round_half_up_cents(
        Decimal(direct) * ESCALATION_RATE_PER_YEAR * Decimal(years)
    )
    pct = expected_contingency_pct(
        delineation_confidence, max_exceedance_factor, underwriting=underwriting
    )
    contingency = round_half_up_cents(Decimal(direct + escalation) * pct)
    subtotal = direct + escalation + contingency
    oversight = min(
        round_half_up_cents(Decimal(subtotal) * OVERSIGHT_RATE), OVERSIGHT_CAP_CENTS
    )
    return {
        "direct_cost_cents": direct,
        "escalation_cents": escalation,
        "contingency_pct": pct,
        "contingency_cents": contingency,
        "oversight_cents": oversight,
        "total_cents": direct + escalation + contingency + oversight,
    }


def expected_placement(underwriting_estimate_cents: int) -> dict:
    """Derive the cap placement from the pre-premium underwriting estimate alone."""
    attachment = round_half_up_cents(
        Decimal(underwriting_estimate_cents) * ATTACHMENT_FACTOR
    )
    buffer_layer = attachment - underwriting_estimate_cents
    limit = ceil_to_step(
        round_half_up_cents(
            Decimal(underwriting_estimate_cents) * LIMIT_SHARE_OF_ESTIMATE
        ),
        LIMIT_ROUNDING_STEP_CENTS,
    )
    ratio = Decimal(limit) / Decimal(underwriting_estimate_cents)
    if ratio <= RATE_TIER_LOW_RATIO:
        rate = RATE_LOW
    elif ratio <= RATE_TIER_MID_RATIO:
        rate = RATE_MID
    else:
        rate = RATE_HIGH
    base_premium = round_half_up_cents(Decimal(limit) * rate)
    premium = max(
        MIN_PREMIUM_CENTS,
        round_half_up_cents(Decimal(base_premium) * (Decimal(1) + BROKER_FEE_RATE)),
    )
    return {
        "attachment_point_cents": attachment,
        "buffer_layer_cents": buffer_layer,
        "limit_cents": limit,
        "rate_applied": rate,
        "premium_cents": premium,
    }


def expected_goal_ugl(
    screening_level_ugl,
    basis: str,
    intended_reuse: str,
    media: str,
    control_credit_type: Optional[str],
    contaminant_count_in_media: int,
) -> dict:
    """Derive one cleanup goal, rounding once on the final selected value."""
    scenario = "RESIDENTIAL" if basis == "UNRESTRICTED" else intended_reuse
    scenario_goal = Decimal(str(screening_level_ugl)) * SCENARIO_MULTIPLIER[scenario]
    credit = (
        CONTROL_CREDIT[control_credit_type] if basis == "RESTRICTED" else Decimal("1.0")
    )
    credited = scenario_goal * credit
    attenuated = credited / MEDIA_ATTENUATION_DIVISOR[media]
    cap = CUMULATIVE_RISK_BUDGET_UGL / Decimal(max(1, contaminant_count_in_media))
    candidate = max(PRACTICAL_QUANT_FLOOR_UGL, min(attenuated, cap))
    return {
        "goal_ugl": round_half_up(candidate, 2),
        "cumulative_cap_applied": bool(
            cap < attenuated and cap > PRACTICAL_QUANT_FLOOR_UGL
        ),
    }


def expected_compliance_pct(
    current_weight: int, satisfied_weight: int, at_risk_weight: int, total_weight: int
) -> Decimal:
    """Weighted compliance: at-risk counts half, lapsed counts nothing."""
    if total_weight == 0:
        return Decimal("1.0")
    numerator = (
        Decimal(current_weight)
        + Decimal(satisfied_weight)
        + Decimal("0.5") * Decimal(at_risk_weight)
    )
    return round_half_up(numerator / Decimal(total_weight), 4)


def expected_waterfall(
    need_cents: int, awards: Iterable[dict], line_cents_by_category: dict
) -> dict:
    """
    Replay the priority waterfall.

    ``awards`` must already be ordered by ``program_priority`` ascending with creation
    order as the tie-break, and each entry carries ``id``, ``max_award_cents``,
    ``max_share_pct``, ``match_requirement_pct`` and ``eligible_cost_categories``.
    """
    remaining = need_cents
    allocations = []
    match_total = 0
    for award in awards:
        eligible_base = sum(
            line_cents_by_category.get(category, 0)
            for category in award["eligible_cost_categories"]
        )
        share_cap = round_half_up_cents(
            Decimal(eligible_base) * Decimal(str(award["max_share_pct"]))
        )
        allocated = min(award["max_award_cents"], share_cap, remaining)
        remaining -= allocated
        allocations.append(
            {"funding_award_id": award["id"], "allocated_cents": allocated}
        )
        match_total += round_half_up_cents(
            Decimal(allocated) * Decimal(str(award["match_requirement_pct"]))
        )
    return {
        "allocations": allocations,
        "unfunded_gap_cents": remaining,
        "local_match_required_cents": match_total,
    }
