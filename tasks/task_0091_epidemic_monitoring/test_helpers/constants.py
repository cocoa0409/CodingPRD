"""Domain thresholds and numeric constants from the PRD.

These constants encode numeric values the PRD pins in §2.9 (precision /
time semantics) and §3.* (per-workflow calculations).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Case reporting (PRD §3.2 — "the report-window constant — 24 hours from onset")
# ---------------------------------------------------------------------------
REPORT_LIMIT_HOURS = 24


# ---------------------------------------------------------------------------
# Regional risk tier — case_density_risk_score (PRD §3.6)
# ---------------------------------------------------------------------------
TIER_WINDOW_DAYS = 14
W_CONFIRMED = 3
W_ASYMPTOMATIC = 1
W_CHAIN = 5
TIER_HIGH_THRESHOLD = 50.00
TIER_MEDIUM_THRESHOLD = 10.00


# ---------------------------------------------------------------------------
# Per-person exposure score — contact_exposure_score (PRD §3.3, §3.8)
# ---------------------------------------------------------------------------
EXPOSURE_WINDOW_DAYS = 14
CLOSE_DISTANCE_METERS = 1.5
DURATION_DENOM_MINUTES = 60
DURATION_CAP = 4
CLOSE_RAW_THRESHOLD = 5.0
EVENT_WEIGHT_HOUSEHOLD = 10
EVENT_WEIGHT_COWORKER = 6
EVENT_WEIGHT_VENUE = 4
EVENT_WEIGHT_TRANSIT = 2


# ---------------------------------------------------------------------------
# Supply allocation — supply_allocation_distribution (PRD §3.7)
# ---------------------------------------------------------------------------
TIER_WEIGHT_HIGH = 100
TIER_WEIGHT_MEDIUM = 30
TIER_WEIGHT_LOW = 0
CATEGORY_WEIGHT_PPE = 5
CATEGORY_WEIGHT_TEST_KIT = 3
CATEGORY_WEIGHT_MEDICATION = 8
CATEGORY_WEIGHT_VACCINE = 6


# ---------------------------------------------------------------------------
# Isolation release & duration (PRD §3.4)
# ---------------------------------------------------------------------------
ISOLATION_MIN_DAYS_CENTRALIZED = 14
ISOLATION_MIN_DAYS_HOME = 10
ISOLATION_MIN_DAYS_MEDICAL_OBSERVATION = 7
REQUIRED_NEGATIVE_TESTS = 2
ABNORMAL_WINDOW_DAYS = 3
EXTENSION_DAYS = 7


# ---------------------------------------------------------------------------
# Tracing SLA (PRD §3.3)
# ---------------------------------------------------------------------------
SLA_SOFT_OVERDUE_HOURS = 12
TRACING_SLA_HOURS = 72  # used internally by fixtures; PRD prose covers SOFT/HARD boundary


# ---------------------------------------------------------------------------
# Test validity windows — PRD §3.5 narrative pins per-modality validity window.
# Values consistent with the difficulty-design recipe ("TEST_VALIDITY_HOURS[PCR]=72").
# ---------------------------------------------------------------------------
TEST_VALIDITY_HOURS_PCR = 72
TEST_VALIDITY_HOURS_ANTIGEN = 24
TEST_VALIDITY_HOURS_ANTIBODY = 168


# ---------------------------------------------------------------------------
# Bulletin (PRD §3.9)
# ---------------------------------------------------------------------------
BULLETIN_ARCHIVE_DAYS = 30


# ---------------------------------------------------------------------------
# Misc time conversion
# ---------------------------------------------------------------------------
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600


TEST_DEFAULTS = {
    "POPULATION": 100000,
    "FACILITY_CAPACITY": 5,
    "RESERVE_QUANTITY": 100,
    "FEVER_THRESHOLD": 37.5,
}


__all__ = [
    "REPORT_LIMIT_HOURS",
    "TIER_WINDOW_DAYS",
    "W_CONFIRMED",
    "W_ASYMPTOMATIC",
    "W_CHAIN",
    "TIER_HIGH_THRESHOLD",
    "TIER_MEDIUM_THRESHOLD",
    "EXPOSURE_WINDOW_DAYS",
    "CLOSE_DISTANCE_METERS",
    "DURATION_DENOM_MINUTES",
    "DURATION_CAP",
    "CLOSE_RAW_THRESHOLD",
    "EVENT_WEIGHT_HOUSEHOLD",
    "EVENT_WEIGHT_COWORKER",
    "EVENT_WEIGHT_VENUE",
    "EVENT_WEIGHT_TRANSIT",
    "TIER_WEIGHT_HIGH",
    "TIER_WEIGHT_MEDIUM",
    "TIER_WEIGHT_LOW",
    "CATEGORY_WEIGHT_PPE",
    "CATEGORY_WEIGHT_TEST_KIT",
    "CATEGORY_WEIGHT_MEDICATION",
    "CATEGORY_WEIGHT_VACCINE",
    "ISOLATION_MIN_DAYS_CENTRALIZED",
    "ISOLATION_MIN_DAYS_HOME",
    "ISOLATION_MIN_DAYS_MEDICAL_OBSERVATION",
    "REQUIRED_NEGATIVE_TESTS",
    "ABNORMAL_WINDOW_DAYS",
    "EXTENSION_DAYS",
    "SLA_SOFT_OVERDUE_HOURS",
    "TRACING_SLA_HOURS",
    "TEST_VALIDITY_HOURS_PCR",
    "TEST_VALIDITY_HOURS_ANTIGEN",
    "TEST_VALIDITY_HOURS_ANTIBODY",
    "BULLETIN_ARCHIVE_DAYS",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "TEST_DEFAULTS",
]
