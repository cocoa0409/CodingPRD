"""Numeric and textual constants declared by the PRD.

Every value here is copied from an explicit PRD statement so that tests never
re-derive a threshold from an implementation.
"""

from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# --------------------------------------------------------------------------
# Discipline alignment scores (PRD 2.9)
# --------------------------------------------------------------------------
ALIGNMENT_SAME_NODE = 1.0000
ALIGNMENT_ONE_LEVEL = 0.7100
ALIGNMENT_SIBLING = 0.6500
ALIGNMENT_CODE_PREFIX = 0.4000
ALIGNMENT_NONE = 0.0000
ALIGNMENT_PASS_THRESHOLD = 0.70

# Default graduate coursework threshold for a discipline (PRD 3.1)
DEFAULT_MIN_GRADUATE_CREDIT_HOURS = 18

# --------------------------------------------------------------------------
# Program defaults (PRD 3.1)
# --------------------------------------------------------------------------
DEFAULT_MIN_TERMINAL_RATIO = 0.75

# --------------------------------------------------------------------------
# Teaching-load ceilings per employment class (PRD 3.4)
# --------------------------------------------------------------------------
MAX_TERM_CREDIT_HOURS = {
    "FULL_TIME": 15,
    "CLINICAL": 12,
    "ADJUNCT": 9,
    "GRADUATE_ASSISTANT": 6,
}

# --------------------------------------------------------------------------
# Professional-development requirements (PRD 3.8)
# --------------------------------------------------------------------------
PD_REQUIRED_HOURS = {
    "FULL_TIME": 40,
    "CLINICAL": 30,
    "ADJUNCT": 20,
    "GRADUATE_ASSISTANT": 10,
}
PD_CYCLE_DAYS = 1095
PD_RELEVANCE_THRESHOLD = 0.70

# --------------------------------------------------------------------------
# Credential-evaluation fee (PRD 3.3)
# --------------------------------------------------------------------------
FEE_FREE_PAGES = 4
FEE_BRACKET_A_PAGES = 8
FEE_BRACKET_A_RATE = 240
FEE_BRACKET_B_PAGES = 12
FEE_BRACKET_B_RATE = 180
FEE_BRACKET_C_RATE = 120
FEE_BASE_CENTS = 9000
FEE_FOREIGN_SURCHARGE_CENTS = 2500
FEE_EXPEDITED_MULTIPLIER = Decimal("1.45")
FEE_STANDARD_MULTIPLIER = Decimal("1.00")
FEE_FLOOR_CENTS = 15000
FEE_CAP_CENTS = 95000

# --------------------------------------------------------------------------
# Tested-experience score (PRD 3.5)
# --------------------------------------------------------------------------
TE_YEARS_DIVISOR = 8
TE_CODES_DIVISOR = 4
TE_WEIGHT_YEARS = Decimal("0.50")
TE_WEIGHT_CERTIFICATION = Decimal("0.30")
TE_WEIGHT_CODES = Decimal("0.20")
TE_CERTIFICATION_FACTOR = {
    "NONE": Decimal("0.00"),
    "PRACTITIONER": Decimal("0.50"),
    "ADVANCED": Decimal("0.75"),
    "BOARD_CERTIFIED": Decimal("1.00"),
}
TE_MIN_YEARS = 3
TE_MIN_SCORE = 0.70

# --------------------------------------------------------------------------
# Adequacy bands (PRD 3.6)
# --------------------------------------------------------------------------
ADEQUACY_AT_RISK_BAND = 0.15

# --------------------------------------------------------------------------
# Accreditor risk index (PRD 3.9)
# --------------------------------------------------------------------------
RISK_WEIGHT_UNQUALIFIED = Decimal("0.40")
RISK_WEIGHT_DOSSIER = Decimal("0.25")
RISK_WEIGHT_EXCEPTION_PERSISTENCE = Decimal("0.20")
RISK_WEIGHT_ADEQUACY_GAP = Decimal("0.15")
RISK_TIER_LOW_CEILING = 30
RISK_TIER_MODERATE_CEILING = 60
RISK_TIER_MULTIPLIER = {
    "LOW": Decimal("1.00"),
    "MODERATE": Decimal("1.10"),
    "HIGH": Decimal("1.25"),
}
RISK_INDEX_CAP = 100.00
RISK_RESPONSE_DAYS = {"LOW": 90, "MODERATE": 60, "HIGH": 30}

# --------------------------------------------------------------------------
# Teaching-block conflict buffers (PRD 3.4)
# --------------------------------------------------------------------------
TRAVEL_BUFFER_CROSS_BUILDING_MINUTES = 15
TRAVEL_BUFFER_SAME_BUILDING_MINUTES = 0
MINUTE_OF_DAY_MIN = 0
MINUTE_OF_DAY_MAX_START = 1439
MINUTE_OF_DAY_MAX_END = 1440

# --------------------------------------------------------------------------
# Rounding helpers matching PRD 2.6
# --------------------------------------------------------------------------
SCORE_PLACES = Decimal("0.0001")
RISK_PLACES = Decimal("0.01")
HOURS_PLACES = Decimal("0.1")


def round_half_up(value, places: Decimal) -> Decimal:
    """Round ``value`` half-up to the quantum given by ``places``."""
    return Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)


def evaluation_fee_cents(page_count: int, service_level: str) -> int:
    """Recompute the PRD 3.3 evaluation fee entirely from the PRD algorithm."""
    billable = max(0, page_count - FEE_FREE_PAGES)
    bracket_a = min(billable, FEE_BRACKET_A_PAGES)
    bracket_b = min(max(billable - FEE_BRACKET_A_PAGES, 0), FEE_BRACKET_B_PAGES)
    bracket_c = max(billable - FEE_BRACKET_A_PAGES - FEE_BRACKET_B_PAGES, 0)
    page_charge = (
        bracket_a * FEE_BRACKET_A_RATE
        + bracket_b * FEE_BRACKET_B_RATE
        + bracket_c * FEE_BRACKET_C_RATE
    )
    subtotal = FEE_BASE_CENTS + FEE_FOREIGN_SURCHARGE_CENTS + page_charge
    multiplier = (
        FEE_EXPEDITED_MULTIPLIER
        if service_level == "EXPEDITED"
        else FEE_STANDARD_MULTIPLIER
    )
    raw = int(round_half_up(Decimal(subtotal) * multiplier, Decimal("1")))
    return min(max(raw, FEE_FLOOR_CENTS), FEE_CAP_CENTS)


def tested_experience_score(
    documented_years_experience: int,
    industry_certification_level: str,
    alternative_credential_codes,
) -> float:
    """Recompute the PRD 3.5 tested-experience score from the PRD formula."""
    years_factor = min(
        Decimal(documented_years_experience) / Decimal(TE_YEARS_DIVISOR), Decimal(1)
    )
    cert_factor = TE_CERTIFICATION_FACTOR[industry_certification_level]
    distinct_codes = len(set(alternative_credential_codes or []))
    codes_factor = min(Decimal(distinct_codes) / Decimal(TE_CODES_DIVISOR), Decimal(1))
    raw = (
        years_factor * TE_WEIGHT_YEARS
        + cert_factor * TE_WEIGHT_CERTIFICATION
        + codes_factor * TE_WEIGHT_CODES
    )
    return float(round_half_up(raw, SCORE_PLACES))


NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"
