"""Domain thresholds and numeric constants from PRD §3.

These are the literal numbers PRD pins. Keeping them in one module
guarantees that boundary tests share the SAME constant as the
implementation should — drift is detected by tests, not hidden.
"""
from __future__ import annotations

from typing import Dict, List


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Trip budget / per-diem — PRD §3.7
# ---------------------------------------------------------------------------
FIRST_LAST_DAY_FRACTION = 0.75


# ---------------------------------------------------------------------------
# Mileage — PRD §3.9
# ---------------------------------------------------------------------------
IRS_BUSINESS_RATE_CENTS = 67          # cents per mile
MILEAGE_OVERLAP_THRESHOLD = 30.0      # miles
MILEAGE_PERSONAL_OVERLAP_RATE_CENTS = 21  # cents per mile beyond threshold


# ---------------------------------------------------------------------------
# Meal itemization shares — PRD §3.8
# ---------------------------------------------------------------------------
MEAL_BREAKFAST_SHARE = 0.25
MEAL_LUNCH_SHARE = 0.30
MEAL_DINNER_SHARE = 0.45
MEAL_INCIDENTAL_SHARE = 0.05

MEAL_SHARES: Dict[str, float] = {
    "BREAKFAST": MEAL_BREAKFAST_SHARE,
    "LUNCH": MEAL_LUNCH_SHARE,
    "DINNER": MEAL_DINNER_SHARE,
    "INCIDENTAL": MEAL_INCIDENTAL_SHARE,
}


# ---------------------------------------------------------------------------
# Rental car CDW — PRD §3.10
# ---------------------------------------------------------------------------
RENTAL_DAILY_CAP_CENTS = 6500
CDW_DAILY_CAP_CENTS = 1500
CORPORATE_CDW_STATES: List[str] = ["CA", "TX", "NY", "FL", "WA"]


# ---------------------------------------------------------------------------
# Flight LLF — PRD §3.11
# ---------------------------------------------------------------------------
LLF_VARIANCE_TOLERANCE_CENTS = 10000  # $100


# ---------------------------------------------------------------------------
# Receipt requirement — PRD §3.4
# ---------------------------------------------------------------------------
RECEIPT_REQUIRED_AMOUNT_CENTS = 7500           # $75 — strict-greater-than
RECEIPT_REQUIRED_CATEGORIES = ["LODGING", "RENTAL_CAR", "FLIGHT"]


# ---------------------------------------------------------------------------
# OOP escalation — PRD §3.5
# ---------------------------------------------------------------------------
OOP_FINAL_ESCALATION_AMOUNT_CENTS = 100000  # $1000


# ---------------------------------------------------------------------------
# OCR thresholds — PRD §3.3
# ---------------------------------------------------------------------------
OCR_CONFIDENCE_VERIFY_THRESHOLD = 0.80
OCR_CONFIDENCE_WAIVE_THRESHOLD = 0.60
OCR_MEAL_WAIVE_TOLERANCE_CENTS = 200


# ---------------------------------------------------------------------------
# Field length / range constraints — PRD §3
# ---------------------------------------------------------------------------
TRIP_PURPOSE_MIN_LEN = 1
TRIP_PURPOSE_MAX_LEN = 500
OOP_JUSTIFICATION_MIN_LEN = 10
OOP_JUSTIFICATION_MAX_LEN = 1000
OCR_CONFIDENCE_MIN = 0.00
OCR_CONFIDENCE_MAX = 1.00


# ---------------------------------------------------------------------------
# Test defaults — convenient starting values for fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: Dict[str, object] = {
    "TRIP_DESTINATION_CITY": "Boston",
    "TRIP_DESTINATION_STATE": "MA",
    "TRIP_ORIGIN_CITY": "Seattle",
    "TRIP_ORIGIN_STATE": "WA",
    "TRIP_START_DATE": "2025-06-02T00:00:00.000Z",
    "TRIP_END_DATE": "2025-06-04T00:00:00.000Z",
    "RATE_LODGING_CAP_CENTS": 28800,
    "RATE_MIE_CAP_CENTS": 8000,
    "RATE_EFFECTIVE_FROM": "2025-06-01T00:00:00.000Z",
    "RATE_EFFECTIVE_TO": "2025-07-01T00:00:00.000Z",
    "DEFAULT_TRIP_PURPOSE": "Q2 customer site visit",
    "DEFAULT_COST_CENTER": "CC-1000",
    "DEFAULT_HOME_STATE": "WA",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "FIRST_LAST_DAY_FRACTION",
    "IRS_BUSINESS_RATE_CENTS",
    "MILEAGE_OVERLAP_THRESHOLD",
    "MILEAGE_PERSONAL_OVERLAP_RATE_CENTS",
    "MEAL_BREAKFAST_SHARE",
    "MEAL_LUNCH_SHARE",
    "MEAL_DINNER_SHARE",
    "MEAL_INCIDENTAL_SHARE",
    "MEAL_SHARES",
    "RENTAL_DAILY_CAP_CENTS",
    "CDW_DAILY_CAP_CENTS",
    "CORPORATE_CDW_STATES",
    "LLF_VARIANCE_TOLERANCE_CENTS",
    "RECEIPT_REQUIRED_AMOUNT_CENTS",
    "RECEIPT_REQUIRED_CATEGORIES",
    "OOP_FINAL_ESCALATION_AMOUNT_CENTS",
    "OCR_CONFIDENCE_VERIFY_THRESHOLD",
    "OCR_CONFIDENCE_WAIVE_THRESHOLD",
    "OCR_MEAL_WAIVE_TOLERANCE_CENTS",
    "TRIP_PURPOSE_MIN_LEN",
    "TRIP_PURPOSE_MAX_LEN",
    "OOP_JUSTIFICATION_MIN_LEN",
    "OOP_JUSTIFICATION_MAX_LEN",
    "OCR_CONFIDENCE_MIN",
    "OCR_CONFIDENCE_MAX",
    "TEST_DEFAULTS",
]
