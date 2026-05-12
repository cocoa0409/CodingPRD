"""Domain thresholds — numeric constants from PRD calculations and rules."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Triage scoring (PRD §3.4)
# ---------------------------------------------------------------------------
EMERGENCY_THRESHOLD: float = 8.0
URGENT_THRESHOLD: float = 5.0
AGE_PEDIATRIC_DAYS: int = 90
AGE_GERIATRIC_DAYS: int = 4380

SPECIES_FACTOR = {
    "DOG": 1.0,
    "CAT": 1.0,
    "RABBIT": 1.2,
    "BIRD": 1.3,
    "OTHER": 1.1,
}


# ---------------------------------------------------------------------------
# Hospitalization (PRD §3.8)
# ---------------------------------------------------------------------------
ADMISSION_HOLD_CENTS: int = 50_000
CAGE_CAPACITY_MIN: int = 1
CAGE_CAPACITY_MAX: int = 4


# ---------------------------------------------------------------------------
# Bill package tiers (PRD §3.9)
# ---------------------------------------------------------------------------
DENTAL_PKG_TIERS = [
    (50_000, 15),   # gross >= 500.00 → 15%
    (20_000, 10),   # gross >= 200.00 → 10%
    (0, 5),         # otherwise 5%
]
SURGERY_PKG_TIERS = [
    (150_000, 20),  # gross >= 1500.00 → 20%
    (0, 12),        # otherwise 12%
]


# ---------------------------------------------------------------------------
# Vaccine (PRD §3.3)
# ---------------------------------------------------------------------------
VACCINE_AGE_MIN_DAYS_MIN: int = 0
VACCINE_AGE_MIN_DAYS_MAX: int = 7300
BOOSTER_INTERVAL_MIN: int = 7
BOOSTER_INTERVAL_MAX: int = 1825


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — non-binding values that satisfy field constraints.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "OWNER_NAME": "Test Owner",
    "PET_NAME": "Test Pet",
    "PET_WEIGHT_KG": 10.0,
    "DEFAULT_BIRTH_DATE": "2024-01-01",
    "DEFAULT_SYMPTOM": "vomiting and lethargy",
    "DEFAULT_SEVERITY": 5,
    "DEFAULT_NOTES": "Standard consultation notes for the case.",
    "DEFAULT_DIAGNOSIS_CODE": "K30",
    "DEFAULT_TREATMENT_PLAN": "Rest, hydration, and follow-up in 7 days.",
}


__all__ = [
    "EMERGENCY_THRESHOLD",
    "URGENT_THRESHOLD",
    "AGE_PEDIATRIC_DAYS",
    "AGE_GERIATRIC_DAYS",
    "SPECIES_FACTOR",
    "ADMISSION_HOLD_CENTS",
    "CAGE_CAPACITY_MIN",
    "CAGE_CAPACITY_MAX",
    "DENTAL_PKG_TIERS",
    "SURGERY_PKG_TIERS",
    "VACCINE_AGE_MIN_DAYS_MIN",
    "VACCINE_AGE_MIN_DAYS_MAX",
    "BOOSTER_INTERVAL_MIN",
    "BOOSTER_INTERVAL_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "TEST_DEFAULTS",
]
