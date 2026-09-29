"""Business constants transcribed from the PRD.

Program parameter defaults come from §3.1, the size-adjustment table and tier
rules from §3.2, the quality-score constants from §3.3, the conditional
reduction from §3.5, the travel buffer from §3.8, and the logical clock's
starting instant from §2.5.
"""

from __future__ import annotations

from typing import Dict

# --------------------------------------------------------------------------- #
# Logical clock (§2.5)
# --------------------------------------------------------------------------- #

#  "Before any clock manipulation the logical clock reads exactly
#   2026-08-01T00:00:00Z".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"


# --------------------------------------------------------------------------- #
# Program parameter defaults (§3.1)
# --------------------------------------------------------------------------- #

DEFAULT_PROGRAM_YEAR = 2026
DEFAULT_RESERVATION_TTL_DAYS = 120
DEFAULT_EXTENSION_WINDOW_DAYS = 30
DEFAULT_MAX_EXTENSION_DAYS = 60
DEFAULT_MAX_EXTENSIONS_PER_RESERVATION = 1

DEFAULT_LOW_TIER_CAP_CENTS = 1400000
DEFAULT_MODERATE_TIER_CAP_CENTS = 800000
DEFAULT_STANDARD_TIER_CAP_CENTS = 300000

DEFAULT_LOW_TIER_COST_SHARE_PCT = 1.00
DEFAULT_MODERATE_TIER_COST_SHARE_PCT = 0.50
DEFAULT_STANDARD_TIER_COST_SHARE_PCT = 0.30

DEFAULT_AMI_LOW_THRESHOLD_PCT = 80.0
DEFAULT_AMI_MODERATE_THRESHOLD_PCT = 150.0

DEFAULT_GROUP_CAP_CENTS = 800000
DEFAULT_PANEL_UPGRADE_CAP_CENTS = 400000

DEFAULT_FEDERAL_CREDIT_PCT = 0.30
DEFAULT_FEDERAL_CREDIT_CAP_CENTS = 200000
DEFAULT_MAX_COMBINED_BENEFIT_PCT = 1.00

DEFAULT_MAX_REMEDIATIONS_PER_PROJECT = 1
DEFAULT_QUALITY_SUSPENSION_THRESHOLD = 70
DEFAULT_RECERTIFICATION_THRESHOLD = 75

DEFAULT_CATALOG_MAX_QUANTITY = 1
DEFAULT_CATALOG_REQUIRED_PANEL_CAPACITY_AMPS = 0
DEFAULT_CATALOG_UPGRADED_CAPACITY_AMPS = 0
DEFAULT_CREW_CAPACITY = 2

#  Full default parameter set, as asserted on a freshly created program.
PROGRAM_PARAMETER_DEFAULTS: Dict[str, object] = {
    "program_year": DEFAULT_PROGRAM_YEAR,
    "reservation_ttl_days": DEFAULT_RESERVATION_TTL_DAYS,
    "extension_window_days": DEFAULT_EXTENSION_WINDOW_DAYS,
    "max_extension_days": DEFAULT_MAX_EXTENSION_DAYS,
    "max_extensions_per_reservation": DEFAULT_MAX_EXTENSIONS_PER_RESERVATION,
    "low_tier_cap_cents": DEFAULT_LOW_TIER_CAP_CENTS,
    "moderate_tier_cap_cents": DEFAULT_MODERATE_TIER_CAP_CENTS,
    "standard_tier_cap_cents": DEFAULT_STANDARD_TIER_CAP_CENTS,
    "ami_low_threshold_pct": DEFAULT_AMI_LOW_THRESHOLD_PCT,
    "ami_moderate_threshold_pct": DEFAULT_AMI_MODERATE_THRESHOLD_PCT,
    "group_cap_cents": DEFAULT_GROUP_CAP_CENTS,
    "panel_upgrade_cap_cents": DEFAULT_PANEL_UPGRADE_CAP_CENTS,
    "federal_credit_cap_cents": DEFAULT_FEDERAL_CREDIT_CAP_CENTS,
    "max_remediations_per_project": DEFAULT_MAX_REMEDIATIONS_PER_PROJECT,
    "quality_suspension_threshold": DEFAULT_QUALITY_SUSPENSION_THRESHOLD,
    "recertification_threshold": DEFAULT_RECERTIFICATION_THRESHOLD,
}


# --------------------------------------------------------------------------- #
# Income tier assignment (§3.2)
# --------------------------------------------------------------------------- #

#  "0.70 for one occupant, 0.80 for two, 0.90 for three, 1.00 for four,
#   1.08 for five, 1.16 for six, and 1.24 for seven or more."
SIZE_ADJUSTMENT_FACTORS: Dict[int, float] = {
    1: 0.70,
    2: 0.80,
    3: 0.90,
    4: 1.00,
    5: 1.08,
    6: 1.16,
    7: 1.24,
}
SIZE_ADJUSTMENT_CLAMP = 7
AMI_DECIMAL_PLACES = 1


# --------------------------------------------------------------------------- #
# Incentive computation (§3.5)
# --------------------------------------------------------------------------- #

#  "multiplied by one minus the ten-percent conditional reduction — that is,
#   by 0.90".
CONDITIONAL_REDUCTION_PCT = 0.10
CONDITIONAL_REDUCTION_MULTIPLIER = 0.90


# --------------------------------------------------------------------------- #
# Contractor quality standing (§3.3)
# --------------------------------------------------------------------------- #

ROLLING_WINDOW_SIZE = 10
WEIGHTED_WINDOW_DAYS = 365
QUALITY_POINTS_PASSED = 100
QUALITY_POINTS_CONDITIONAL_PASS = 70
QUALITY_POINTS_FAILED = 0
EMPTY_WINDOW_QUALITY_SCORE = 100
INITIAL_QUALITY_SCORE_ROLLING = 100


# --------------------------------------------------------------------------- #
# Scheduling constraints (§3.7, §3.8)
# --------------------------------------------------------------------------- #

#  "The travel buffer is 45 minutes."
INSPECTOR_TRAVEL_BUFFER_MINUTES = 45
INSPECTOR_WINDOW_CAPACITY = 1

#  Deficiency severity ceiling for the conditional-pass branch (§3.8).
MAX_CONDITIONAL_PASS_SEVERITY = 2
MAX_DEFICIENCY_SEVERITY = 5


# --------------------------------------------------------------------------- #
# Pagination (§2.3)
# --------------------------------------------------------------------------- #

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
MIN_PAGE_OFFSET = 0


# --------------------------------------------------------------------------- #
# Shared measure codes used by the fixtures
# --------------------------------------------------------------------------- #

MEASURE_HP_HVAC = "HP-HVAC-01"
MEASURE_HP_DUCT = "HP-DUCT-01"
MEASURE_HPWH = "HPWH-01"
MEASURE_PANEL_200A = "PANEL-200A"
MEASURE_PANEL_400A = "PANEL-400A"
MEASURE_STOVE = "STOVE-IND-01"
MEASURE_ENV_INS = "ENV-INS-01"


__all__ = [
    "DEFAULT_CLOCK_UTC",
    "DEFAULT_CLOCK_DATE",
    "DEFAULT_PROGRAM_YEAR",
    "DEFAULT_RESERVATION_TTL_DAYS",
    "DEFAULT_EXTENSION_WINDOW_DAYS",
    "DEFAULT_MAX_EXTENSION_DAYS",
    "DEFAULT_MAX_EXTENSIONS_PER_RESERVATION",
    "DEFAULT_LOW_TIER_CAP_CENTS",
    "DEFAULT_MODERATE_TIER_CAP_CENTS",
    "DEFAULT_STANDARD_TIER_CAP_CENTS",
    "DEFAULT_LOW_TIER_COST_SHARE_PCT",
    "DEFAULT_MODERATE_TIER_COST_SHARE_PCT",
    "DEFAULT_STANDARD_TIER_COST_SHARE_PCT",
    "DEFAULT_AMI_LOW_THRESHOLD_PCT",
    "DEFAULT_AMI_MODERATE_THRESHOLD_PCT",
    "DEFAULT_GROUP_CAP_CENTS",
    "DEFAULT_PANEL_UPGRADE_CAP_CENTS",
    "DEFAULT_FEDERAL_CREDIT_PCT",
    "DEFAULT_FEDERAL_CREDIT_CAP_CENTS",
    "DEFAULT_MAX_COMBINED_BENEFIT_PCT",
    "DEFAULT_MAX_REMEDIATIONS_PER_PROJECT",
    "DEFAULT_QUALITY_SUSPENSION_THRESHOLD",
    "DEFAULT_RECERTIFICATION_THRESHOLD",
    "DEFAULT_CATALOG_MAX_QUANTITY",
    "DEFAULT_CATALOG_REQUIRED_PANEL_CAPACITY_AMPS",
    "DEFAULT_CATALOG_UPGRADED_CAPACITY_AMPS",
    "DEFAULT_CREW_CAPACITY",
    "PROGRAM_PARAMETER_DEFAULTS",
    "SIZE_ADJUSTMENT_FACTORS",
    "SIZE_ADJUSTMENT_CLAMP",
    "AMI_DECIMAL_PLACES",
    "CONDITIONAL_REDUCTION_PCT",
    "CONDITIONAL_REDUCTION_MULTIPLIER",
    "ROLLING_WINDOW_SIZE",
    "WEIGHTED_WINDOW_DAYS",
    "QUALITY_POINTS_PASSED",
    "QUALITY_POINTS_CONDITIONAL_PASS",
    "QUALITY_POINTS_FAILED",
    "EMPTY_WINDOW_QUALITY_SCORE",
    "INITIAL_QUALITY_SCORE_ROLLING",
    "INSPECTOR_TRAVEL_BUFFER_MINUTES",
    "INSPECTOR_WINDOW_CAPACITY",
    "MAX_CONDITIONAL_PASS_SEVERITY",
    "MAX_DEFICIENCY_SEVERITY",
    "DEFAULT_PAGE_LIMIT",
    "MIN_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "MIN_PAGE_OFFSET",
    "MEASURE_HP_HVAC",
    "MEASURE_HP_DUCT",
    "MEASURE_HPWH",
    "MEASURE_PANEL_200A",
    "MEASURE_PANEL_400A",
    "MEASURE_STOVE",
    "MEASURE_ENV_INS",
]
