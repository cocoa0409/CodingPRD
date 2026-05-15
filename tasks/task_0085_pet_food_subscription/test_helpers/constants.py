"""Domain thresholds and defaults sourced from PRD §3 calculations.

These constants centralise the numeric values that tests use to build
boundary scenarios and to avoid magic numbers scattered in test code.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------
SECONDS_PER_HOUR: int = 3600
SECONDS_PER_DAY: int = 86_400
HOURS_PER_DAY: int = 24


# ---------------------------------------------------------------------------
# Life-stage derivation (PRD §3.1)
# ---------------------------------------------------------------------------
DOG_PUPPY_MAX_MONTHS: int = 12
DOG_ADULT_MAX_MONTHS: int = 84
CAT_PUPPY_MAX_MONTHS: int = 12
CAT_ADULT_MAX_MONTHS: int = 120


# ---------------------------------------------------------------------------
# Portion calculation (PRD §3.4)
# ---------------------------------------------------------------------------
RER_COEFFICIENT: int = 70
RER_EXPONENT: float = 0.75

ACTIVITY_FACTOR = {
    "LOW": 1.2,
    "MODERATE": 1.6,
    "HIGH": 2.0,
}

LIFE_STAGE_FACTOR = {
    "PUPPY_KITTEN": 1.8,
    "ADULT": 1.0,
    "SENIOR": 0.8,
}


# ---------------------------------------------------------------------------
# Order total (PRD §3.4)
# ---------------------------------------------------------------------------
TRIAL_DISCOUNT: float = 0.5


# ---------------------------------------------------------------------------
# Shipping-fee tiers (PRD §3.4)
# ---------------------------------------------------------------------------
FREE_THRESHOLD_CENTS: int = 8000
MID_THRESHOLD_CENTS: int = 4000
MID_FEE_CENTS: int = 499
HIGH_FEE_CENTS: int = 999


# ---------------------------------------------------------------------------
# Recipe scoring (PRD §3.3)
# ---------------------------------------------------------------------------
VET_PRESCRIBED_BONUS: int = 40
LIFE_STAGE_MATCH: int = 30
PREFERRED_INGREDIENT_WEIGHT: int = 10
AVERSION_PENALTY: int = 5
INTOLERANCE_PENALTY: int = 15


# ---------------------------------------------------------------------------
# Feedback aggregation + suggestion engine (PRD §3.5)
# ---------------------------------------------------------------------------
AGGREGATION_WINDOW: int = 3
MIN_FEEDBACKS_FOR_SUGGESTION: int = 2
WEIGHT_GAIN_THRESHOLD_GRAMS: int = 500


# ---------------------------------------------------------------------------
# Scheduling (PRD §3.4)
# ---------------------------------------------------------------------------
SHIP_LEAD_TIME_HOURS: int = 72
DEFAULT_MODIFICATION_DEADLINE_HOURS: int = 48

CYCLE_DAYS_BY_FREQUENCY = {
    "WEEKLY": 7,
    "BIWEEKLY": 14,
    "MONTHLY": 30,
}


# ---------------------------------------------------------------------------
# Allergen / ingredient vocabularies (PRD §3.1)
# ---------------------------------------------------------------------------
KNOWN_ALLERGENS = [
    "CHICKEN", "BEEF", "FISH", "GRAIN", "DAIRY", "EGG", "SOY",
]
KNOWN_HEALTH_CONDITIONS = ["KIDNEY", "DIABETES", "DENTAL"]
SUPPORTED_COUNTRIES = ["US", "CA", "UK", "AU", "DE", "FR", "JP", "CN"]


# ---------------------------------------------------------------------------
# Test default scalars
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "EMAIL_PREFIX": "owner",
    "EMAIL_DOMAIN": "example.com",
    "DISPLAY_NAME": "Test Owner",
    "PET_NAME": "Buddy",
    "BREED": "Labrador Retriever",
    "WEIGHT_KG": 16.0,
    "ACTIVITY": "MODERATE",
    "KCAL_PER_GRAM": 4.0,
    "UNIT_PRICE_CENTS_PER_100G": 200,
    "WAREHOUSE_CODE": "WH-EAST",
    "REGION": "CA",
    "POSTAL_CODE_US": "94016",
    "COUNTRY_US": "US",
    "BATCH_QUANTITY_GRAMS": 1_000_000,
    "DAILY_CAPACITY": 50,
    "PRIORITY_RANK": 10,
    "MONOTONY_CLASS_A": "M_A",
    "MONOTONY_CLASS_B": "M_B",
    "MONOTONY_CLASS_C": "M_C",
}


__all__ = [
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "HOURS_PER_DAY",
    "DOG_PUPPY_MAX_MONTHS",
    "DOG_ADULT_MAX_MONTHS",
    "CAT_PUPPY_MAX_MONTHS",
    "CAT_ADULT_MAX_MONTHS",
    "RER_COEFFICIENT",
    "RER_EXPONENT",
    "ACTIVITY_FACTOR",
    "LIFE_STAGE_FACTOR",
    "TRIAL_DISCOUNT",
    "FREE_THRESHOLD_CENTS",
    "MID_THRESHOLD_CENTS",
    "MID_FEE_CENTS",
    "HIGH_FEE_CENTS",
    "VET_PRESCRIBED_BONUS",
    "LIFE_STAGE_MATCH",
    "PREFERRED_INGREDIENT_WEIGHT",
    "AVERSION_PENALTY",
    "INTOLERANCE_PENALTY",
    "AGGREGATION_WINDOW",
    "MIN_FEEDBACKS_FOR_SUGGESTION",
    "WEIGHT_GAIN_THRESHOLD_GRAMS",
    "SHIP_LEAD_TIME_HOURS",
    "DEFAULT_MODIFICATION_DEADLINE_HOURS",
    "CYCLE_DAYS_BY_FREQUENCY",
    "KNOWN_ALLERGENS",
    "KNOWN_HEALTH_CONDITIONS",
    "SUPPORTED_COUNTRIES",
    "TEST_DEFAULTS",
]
