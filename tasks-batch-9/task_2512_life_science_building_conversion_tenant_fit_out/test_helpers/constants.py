"""Domain thresholds, published tables and derivation helpers.

Every figure here is stated by the PRD; the helpers reproduce the PRD's own
arithmetic so that a test can express an expected value as a derivation rather
than as an opaque literal.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = "2026-08-01T00:00:00Z"

PROPOSAL_TTL_DAYS = 10
NEGOTIATION_ROUND_LIMIT = 6
VIBRATION_BUFFER_HOURS = 24

# ---------------------------------------------------------------------------
# Floor control area entitlement, derived from floor_number alone
# ---------------------------------------------------------------------------

# floor_number band -> (control_areas_allowed, percent_maq)
FLOOR_CONTROL_AREA_TABLE = {
    1: (4, 100.0),
    2: (3, 75.0),
    3: (3, 75.0),
    4: (2, 50.0),
    5: (2, 50.0),
    6: (2, 50.0),
}
HIGH_FLOOR_CONTROL_AREAS = 2
HIGH_FLOOR_PERCENT_MAQ = 25.0


def control_areas_for_floor(floor_number: int) -> int:
    """control_areas_allowed for a floor number, with no upper bound."""
    if floor_number in FLOOR_CONTROL_AREA_TABLE:
        return FLOOR_CONTROL_AREA_TABLE[floor_number][0]
    return HIGH_FLOOR_CONTROL_AREAS


def percent_maq_for_floor(floor_number: int) -> float:
    """percent_maq for a floor number, with no upper bound."""
    if floor_number in FLOOR_CONTROL_AREA_TABLE:
        return FLOOR_CONTROL_AREA_TABLE[floor_number][1]
    return HIGH_FLOOR_PERCENT_MAQ


# ---------------------------------------------------------------------------
# Suitability scoring
# ---------------------------------------------------------------------------

HEIGHT_FULL_CREDIT_FT = 14.0
HEIGHT_PARTIAL_CREDIT_FT = 12.5
STRUCTURAL_FULL_CREDIT_PSF = 100.0
STRUCTURAL_PARTIAL_CREDIT_PSF = 80.0
UTILITY_FULL_CREDIT_RATIO = 1.25
UTILITY_PARTIAL_CREDIT_RATIO = 1.00

VIBRATION_RANK: Dict[str, int] = {
    "VC_E": 1,
    "VC_D": 2,
    "VC_C": 3,
    "VC_B": 4,
    "VC_A": 5,
}

WEIGHT_HEIGHT = 0.25
WEIGHT_STRUCTURAL = 0.25
WEIGHT_VIBRATION = 0.20
WEIGHT_UTILITY = 0.30

HARD_FAIL_CAP_SCORE = 49.0
VERDICT_SUITABLE_MIN = 75.0
VERDICT_CONDITIONAL_MIN = 50.0

# ---------------------------------------------------------------------------
# Tenant research programmes
# ---------------------------------------------------------------------------

LAB_PREMIUM_PSF: Dict[str, float] = {
    "BSL2_BIOLOGY": 45.00,
    "CHEMISTRY_SYNTHESIS": 62.50,
    "VIVARIUM": 88.00,
    "ANALYTICAL_QC": 30.00,
}

REQUIRED_COMMISSIONING_SCRIPTS: Dict[str, List[str]] = {
    "BSL2_BIOLOGY": ["CONTAINMENT_VERIFICATION", "EXHAUST_AIRFLOW", "IQ", "OQ"],
    "CHEMISTRY_SYNTHESIS": ["EPSS_LOAD_TEST", "EXHAUST_AIRFLOW", "IQ", "OQ"],
    "VIVARIUM": [
        "CONTAINMENT_VERIFICATION",
        "EPSS_LOAD_TEST",
        "EXHAUST_AIRFLOW",
        "IQ",
        "OQ",
        "PQ",
    ],
    "ANALYTICAL_QC": ["IQ", "OQ"],
}

# ---------------------------------------------------------------------------
# Lease economics
# ---------------------------------------------------------------------------

HIGH_FLOOR_STACK_UPLIFT_PSF = 5.00
HIGH_FLOOR_UPLIFT_FROM_FLOOR = 4

VOLUME_CREDIT_TIER_HIGH_FLOOR_USD = 5_000_000.00
VOLUME_CREDIT_TIER_HIGH_PSF = 3.00
VOLUME_CREDIT_TIER_MID_FLOOR_USD = 2_000_000.00
VOLUME_CREDIT_TIER_MID_PSF = 1.50
VOLUME_CREDIT_TIER_NONE_PSF = 0.00

RESTORATION_ESCROW_RATE = 0.10
RESTORATION_ESCROW_CAP_USD = 250_000.00

TI_DRAW_CAP_RATE = 0.30

# ---------------------------------------------------------------------------
# Phase package eligibility
# ---------------------------------------------------------------------------

# premium_class -> (eligible share, premium multiplier)
PREMIUM_CLASS_FACTORS: Dict[str, tuple] = {
    "SHELL": (0.60, 1.00),
    "LAB_MEP": (0.85, 1.18),
    "VIVARIUM": (0.90, 1.275),
    "CLEANROOM": (0.88, 1.22),
}

# ---------------------------------------------------------------------------
# Hazardous materials
# ---------------------------------------------------------------------------

HAZARD_BASE_MAQ_GAL: Dict[str, float] = {
    "FLAMMABLE_IB": 120.0,
    "FLAMMABLE_II": 240.0,
    "CORROSIVE": 500.0,
    "OXIDIZER_2": 250.0,
}

USE_CONDITION_FACTOR: Dict[str, float] = {
    "STORAGE_CABINET": 2.0,
    "CLOSED_SYSTEM_USE": 1.0,
    "OPEN_SYSTEM_USE": 0.5,
}

SPRINKLERED_FACTOR = 2.0
UNSPRINKLERED_FACTOR = 1.0

# ---------------------------------------------------------------------------
# Restoration liability
# ---------------------------------------------------------------------------

PERMIT_DECOMMISSIONING_FEE_USD = 250.00
PERMIT_PER_GALLON_FEE_USD = 3.00

# ---------------------------------------------------------------------------
# Rounding helpers (half up, as the PRD requires everywhere)
# ---------------------------------------------------------------------------


def round_half_up(value, places: int = 2) -> float:
    """Round half up to ``places`` decimal places, away from zero at the midpoint."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def allowance_per_control_area_gal(
    hazard_class: str,
    floor_number: int,
    sprinklered: bool,
    use_condition: str,
) -> float:
    """The per-control-area allowance from base MAQ, percent, sprinklers and use."""
    base = HAZARD_BASE_MAQ_GAL[hazard_class]
    percent = percent_maq_for_floor(floor_number) / 100.0
    sprinkler = SPRINKLERED_FACTOR if sprinklered else UNSPRINKLERED_FACTOR
    return round_half_up(base * percent * sprinkler * USE_CONDITION_FACTOR[use_condition])


def aggregate_allowance_gal(
    hazard_class: str,
    floor_number: int,
    sprinklered: bool,
    use_condition: str,
) -> float:
    """The whole-floor allowance: per-control-area allowance times the entitlement."""
    per_area = allowance_per_control_area_gal(
        hazard_class, floor_number, sprinklered, use_condition
    )
    return round_half_up(per_area * control_areas_for_floor(floor_number))


def phase_ti_eligible_usd(hard_cost_usd: float, premium_class: str) -> float:
    """hard_cost_usd times the class share times the class multiplier, at 2dp."""
    share, multiplier = PREMIUM_CLASS_FACTORS[premium_class]
    return round_half_up(hard_cost_usd * share * multiplier)


def volume_credit_psf(provisional_authorized_ti_usd: float) -> float:
    """The credit tier selected from the pre-credit authorisation."""
    if provisional_authorized_ti_usd >= VOLUME_CREDIT_TIER_HIGH_FLOOR_USD:
        return VOLUME_CREDIT_TIER_HIGH_PSF
    if provisional_authorized_ti_usd >= VOLUME_CREDIT_TIER_MID_FLOOR_USD:
        return VOLUME_CREDIT_TIER_MID_PSF
    return VOLUME_CREDIT_TIER_NONE_PSF


def lease_economics(
    accepted_allowance_psf: float,
    lab_premium_psf: float,
    premises_floor_number: int,
    rentable_sf: int,
) -> Dict[str, float]:
    """Reproduce the seven ordered steps of the allowance authorisation."""
    applied = lab_premium_psf + (
        HIGH_FLOOR_STACK_UPLIFT_PSF
        if premises_floor_number >= HIGH_FLOOR_UPLIFT_FROM_FLOOR
        else 0.0
    )
    subtotal = accepted_allowance_psf + applied
    provisional = round_half_up(subtotal * rentable_sf)
    credit = volume_credit_psf(provisional)
    final_psf = round_half_up(subtotal - credit)
    authorized = round_half_up(final_psf * rentable_sf)
    escrow = min(
        round_half_up(RESTORATION_ESCROW_RATE * authorized), RESTORATION_ESCROW_CAP_USD
    )
    # The per-square-foot subtotal is an intermediate of the formula, not a
    # response-visible lease attribute, so it is deliberately not returned here.
    return {
        "lab_premium_psf_applied": applied,
        "provisional_authorized_ti_usd": provisional,
        "volume_credit_psf": credit,
        "final_allowance_psf": final_psf,
        "ti_authorized_usd": authorized,
        "restoration_escrow_required_usd": escrow,
    }


def utility_headroom_ratio(
    exhaust_riser_capacity_cfm: float,
    required_exhaust_cfm: float,
    emergency_power_capacity_kw: float,
    required_power_kw: float,
) -> float:
    """The smaller of the two nameplate quotients, at four decimal places."""
    return round_half_up(
        min(
            exhaust_riser_capacity_cfm / required_exhaust_cfm,
            emergency_power_capacity_kw / required_power_kw,
        ),
        4,
    )


def weighted_suitability_score(
    height_credit: int,
    structural_credit: int,
    vibration_credit: int,
    utility_credit: int,
) -> float:
    """The weighted sum, rounded half up to one decimal place exactly once."""
    return round_half_up(
        height_credit * WEIGHT_HEIGHT
        + structural_credit * WEIGHT_STRUCTURAL
        + vibration_credit * WEIGHT_VIBRATION
        + utility_credit * WEIGHT_UTILITY,
        1,
    )


THRESHOLDS = {
    "HEIGHT_FULL_CREDIT_FT": HEIGHT_FULL_CREDIT_FT,
    "HEIGHT_PARTIAL_CREDIT_FT": HEIGHT_PARTIAL_CREDIT_FT,
    "STRUCTURAL_FULL_CREDIT_PSF": STRUCTURAL_FULL_CREDIT_PSF,
    "STRUCTURAL_PARTIAL_CREDIT_PSF": STRUCTURAL_PARTIAL_CREDIT_PSF,
    "UTILITY_FULL_CREDIT_RATIO": UTILITY_FULL_CREDIT_RATIO,
    "UTILITY_PARTIAL_CREDIT_RATIO": UTILITY_PARTIAL_CREDIT_RATIO,
    "HARD_FAIL_CAP_SCORE": HARD_FAIL_CAP_SCORE,
    "VERDICT_SUITABLE_MIN": VERDICT_SUITABLE_MIN,
    "VERDICT_CONDITIONAL_MIN": VERDICT_CONDITIONAL_MIN,
    "PROPOSAL_TTL_DAYS": PROPOSAL_TTL_DAYS,
    "NEGOTIATION_ROUND_LIMIT": NEGOTIATION_ROUND_LIMIT,
    "VIBRATION_BUFFER_HOURS": VIBRATION_BUFFER_HOURS,
    "RESTORATION_ESCROW_RATE": RESTORATION_ESCROW_RATE,
    "RESTORATION_ESCROW_CAP_USD": RESTORATION_ESCROW_CAP_USD,
    "TI_DRAW_CAP_RATE": TI_DRAW_CAP_RATE,
    "HIGH_FLOOR_STACK_UPLIFT_PSF": HIGH_FLOOR_STACK_UPLIFT_PSF,
    "PERMIT_DECOMMISSIONING_FEE_USD": PERMIT_DECOMMISSIONING_FEE_USD,
    "PERMIT_PER_GALLON_FEE_USD": PERMIT_PER_GALLON_FEE_USD,
}
