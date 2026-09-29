"""Literal thresholds, bases and canonical sample data drawn from the PRD.

Nothing here is invented: every number is quoted from the PRD section named in
the comment beside it.  Tests import these names instead of repeating magic
numbers so that the pricing and welfare arithmetic stays readable.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.7)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Travel fee (PRD §3.8)
# ---------------------------------------------------------------------------

VOLUMETRIC_DIVISOR = 6000
FREE_WEIGHT_ALLOWANCE_KG = 10
WEIGHT_TIER_BREAK_KG = 32
RATE_PER_KG_UP_TO_BREAK = 450
RATE_PER_KG_ABOVE_BREAK = 700
ROUTING_BASE_FEE = {"CABIN": 12500, "CHECKED": 20000, "CARGO": 27500}
SNUB_NOSED_MULTIPLIER = 1.15
LONG_HAUL_MULTIPLIER = 1.2
LONG_HAUL_BLOCK_MINUTES_THRESHOLD = 480
IROPS_FEE_PER_ANIMAL = 3500

# ---------------------------------------------------------------------------
# Loyalty tiers (PRD §3.8)
# ---------------------------------------------------------------------------

LOYALTY_TIER_TOP_THRESHOLD = 100000
LOYALTY_TIER_TOP_PCT = 0.10
LOYALTY_TIER_MID_THRESHOLD = 65000
LOYALTY_TIER_MID_PCT = 0.05
LOYALTY_TIER_NONE_PCT = 0

# ---------------------------------------------------------------------------
# Container compliance (PRD §3.4)
# ---------------------------------------------------------------------------

CONTAINER_HEIGHT_CLEARANCE_CM = 8
CONTAINER_LENGTH_MULTIPLIER = 1.15
VENT_PCT_BASE = 8
VENT_PCT_WEIGHT_DIVISOR = 5
VENT_SIDES_SMALL_MAX_KG = 20
VENT_SIDES_MEDIUM_MAX_KG = 32
VENT_SIDES_SMALL = 2
VENT_SIDES_MEDIUM = 3
VENT_SIDES_LARGE = 4
DEFICIENCY_CODE_ORDER = [
    "HEIGHT",
    "LENGTH",
    "VENT_PCT",
    "VENT_SIDES",
    "GROSS_WEIGHT",
    "CABIN_DIM",
    "WHEELS",
]

# ---------------------------------------------------------------------------
# Connection welfare window (PRD §3.5)
# ---------------------------------------------------------------------------

MINIMUM_CONNECTION_MINUTES = {"CABIN": 60, "CHECKED": 90, "CARGO": 120}
MAXIMUM_CONNECTION_MINUTES = 720
WELFARE_CHECK_INTERVAL_MINUTES = 240

# ---------------------------------------------------------------------------
# Leg posture (PRD §3.3)
# ---------------------------------------------------------------------------

RESTRICTED_LOAD_NUMERATOR = 10
RESTRICTED_LOAD_DENOMINATOR = 9

# ---------------------------------------------------------------------------
# Kennel bay projection (PRD §3.7)
# ---------------------------------------------------------------------------

SANITATION_BUFFER_MINUTES = 45
MIN_FEEDING_INTERVAL_MINUTES = 60
MAX_FEEDING_INTERVAL_MINUTES = 720

# ---------------------------------------------------------------------------
# Incident severity and disclosure (PRD §3.9)
# ---------------------------------------------------------------------------

INCIDENT_BASE_SCORE = {"INJURY": 40, "LOSS": 70, "DEATH": 85}
IN_TRANSIT_ADDER = 10
WELFARE_GAP_WEIGHT = 6
WELFARE_COMPONENT_CAP = 12
SEVERITY_SCORE_CAP = 100
DISCLOSURE_SCORE_THRESHOLD = 60
DISCLOSURE_WINDOW_HOURS = {"DEATH": 24, "LOSS": 48, "INJURY": 168}
FINDING_FACTOR = {
    "CARRIER_ATTRIBUTABLE": 1,
    "INDETERMINATE": 0.9,
    "PRE_EXISTING_CONDITION": 0.8,
}
LATE_DISCLOSURE_PENALTY = 20

# ---------------------------------------------------------------------------
# Health documents (PRD §3.6)
# ---------------------------------------------------------------------------

MAX_DOCUMENT_REVISIONS = 3

# ---------------------------------------------------------------------------
# Canonical sample data used across the acceptance workflow
# ---------------------------------------------------------------------------

SPECIES_CODE_DOG = "DOG"
SPECIES_COMMON_NAME_DOG = "Dog"
SPECIES_MAX_CABIN_WEIGHT_KG = 12
SPECIES_MIN_AGE_WEEKS = 16

CONTAINER_MODEL_CODE = "K9-L"
CONTAINER_INTERIOR_HEIGHT_CM = 45
CONTAINER_INTERIOR_LENGTH_CM = 60
CONTAINER_INTERIOR_WIDTH_CM = 40
CONTAINER_TARE_WEIGHT_KG = 7
CONTAINER_VENTILATION_AREA_PCT = 15
CONTAINER_VENTILATED_SIDE_COUNT = 3

STATION_HKG = "HKG"
STATION_LAX = "LAX"
STATION_JFK = "JFK"
STATION_SIN = "SIN"

COUNTRY_HONG_KONG = "HK"
COUNTRY_UNITED_STATES = "US"
COUNTRY_SINGAPORE = "SG"

LEG_AN101_DEPARTURE_UTC = "2026-09-10T02:00:00Z"
LEG_AN101_ARRIVAL_UTC = "2026-09-10T15:00:00Z"
LEG_AN101_BLOCK_MINUTES = 780

DOCUMENT_ISSUED_AT_UTC = "2026-07-20T00:00:00Z"
DOCUMENT_EXPIRES_AT_UTC = "2026-10-01T00:00:00Z"
DESTINATION_MAX_AGE_DAYS_AT_ARRIVAL = 60


# ---------------------------------------------------------------------------
# Arithmetic helpers pinned to the PRD's rounding convention (PRD §2.8)
# ---------------------------------------------------------------------------


def round_half_up(value: float) -> int:
    """Round to the nearest whole unit with halves going away from zero.

    PRD §2.8: "Rounding, where it happens at all, is half up: a value whose
    fractional part is exactly one half rounds away from zero."
    """
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def chargeable_weight_kg(
    basis_weight_kg: float,
    tare_weight_kg: float,
    interior_length_cm: float,
    interior_width_cm: float,
    interior_height_cm: float,
) -> int:
    """Steps one to three of the travel fee (PRD §3.8)."""
    gross = basis_weight_kg + tare_weight_kg
    volumetric = (
        interior_length_cm * interior_width_cm * interior_height_cm
    ) / VOLUMETRIC_DIVISOR
    return math.ceil(max(gross, volumetric))


def weight_component(chargeable_kg: int) -> int:
    """Step three's per-kilogram component (PRD §3.8)."""
    return (
        min(chargeable_kg, WEIGHT_TIER_BREAK_KG) - FREE_WEIGHT_ALLOWANCE_KG
    ) * RATE_PER_KG_UP_TO_BREAK + max(
        chargeable_kg - WEIGHT_TIER_BREAK_KG, 0
    ) * RATE_PER_KG_ABOVE_BREAK


def loyalty_tier_pct(subtotal_amount: int) -> float:
    """Step two of charge assembly (PRD §3.8)."""
    if subtotal_amount >= LOYALTY_TIER_TOP_THRESHOLD:
        return LOYALTY_TIER_TOP_PCT
    if subtotal_amount >= LOYALTY_TIER_MID_THRESHOLD:
        return LOYALTY_TIER_MID_PCT
    return LOYALTY_TIER_NONE_PCT


def required_welfare_check_count(connection_minutes: int) -> int:
    """PRD §3.5 welfare cadence."""
    return 1 + connection_minutes // WELFARE_CHECK_INTERVAL_MINUTES


__all__ = [
    name
    for name in dir()
    if not name.startswith("_") and name not in {"math", "annotations"}
]
