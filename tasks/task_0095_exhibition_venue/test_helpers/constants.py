"""Domain thresholds — numeric constants from PRD calculations.

PRD §3.2 booth_quoted_price: tier base, ISLAND oversize per-cell, corner
multiplier, theme add-on.
PRD §3.3 application_priority_score: sponsor weights, seniority cap and
per-year increment, lottery divisor.
PRD §3.6 work_order_billing: tax rate, cleaning discount.
PRD §3.7 ticket_price: base prices, onsite surcharge, group threshold and
discount.
PRD §3.8 entitlement_make_good: per-tier base and per-entitlement factor.
PRD §3.8 entitlement_fulfillment_score: fulfilled / make-good base / missed
base scores, missed daily decay.
PRD §3.7 posture saturation / recovery thresholds.
PRD §3.1 default objection window hours.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# PRD §3.2 booth_quoted_price constants.
# ---------------------------------------------------------------------------
TIER_BASE_STANDARD_CENTS = 200000
TIER_BASE_PREMIUM_CENTS = 350000
TIER_BASE_ISLAND_CENTS = 600000
ISLAND_OVERSIZE_PER_CELL_PCT = 0.10
ISLAND_OVERSIZE_CELL_THRESHOLD = 4  # multiplier applies only beyond 4 cells
CORNER_MULTIPLIER = 1.15
THEME_ADDON_PREFIX = "PRO_"
THEME_ADDON_CENTS = 50000


# ---------------------------------------------------------------------------
# PRD §3.3 application_priority_score constants.
# ---------------------------------------------------------------------------
SENIORITY_CAP_YEARS = 20
SENIORITY_PER_YEAR = 10
SPONSOR_WEIGHT = {
    "NONE": 0,
    "BRONZE": 100,
    "SILVER": 250,
    "GOLD": 500,
    "PLATINUM": 1000,
}
LOTTERY_DIVISOR = 10000.0
LOTTERY_TOKEN_MAX = 999999


# ---------------------------------------------------------------------------
# PRD §3.6 work_order_billing constants.
# ---------------------------------------------------------------------------
WORK_ORDER_TAX_RATE = 0.06
CLEANING_DISCOUNT_RATE = 0.05
CLEANING_DISCOUNT_MULTIPLIER = 0.95  # 1 - 0.05


# ---------------------------------------------------------------------------
# PRD §3.7 ticket_price constants.
# ---------------------------------------------------------------------------
TICKET_BASE_VISITOR = 5000
TICKET_BASE_PROFESSIONAL_BUYER = 12000
TICKET_BASE_STUDENT = 2500
TICKET_BASE_VIP = 30000
ONSITE_SURCHARGE_MULTIPLIER = 1.20
GROUP_THRESHOLD = 10
GROUP_DISCOUNT_MULTIPLIER = 0.85


# ---------------------------------------------------------------------------
# PRD §3.7 posture saturation / recovery thresholds.
# ---------------------------------------------------------------------------
POSTURE_SATURATION_RATIO = 0.95  # OPEN → RESTRICTED when ratio >= 0.95
POSTURE_RECOVERY_RATIO = 0.90    # RESTRICTED → OPEN when ratio < 0.90


# ---------------------------------------------------------------------------
# PRD §3.8 entitlement_make_good constants.
# ---------------------------------------------------------------------------
MAKE_GOOD_TIER_BASE_CENTS = {
    "BRONZE": 10000,
    "SILVER": 25000,
    "GOLD": 60000,
    "PLATINUM": 120000,
}
MAKE_GOOD_FACTOR = {
    "SIGNAGE": 0.5,
    "PROGRAM_AD": 0.4,
    "LOUNGE": 0.8,
    "SPEAKING_SLOT": 1.0,
    "BRANDED_GIFT": 0.3,
}


# ---------------------------------------------------------------------------
# PRD §3.8 entitlement_fulfillment_score constants.
# ---------------------------------------------------------------------------
FULFILLED_SCORE = 1.0
MAKE_GOOD_BASE_SCORE = 0.5
MISSED_BASE_SCORE = 0.5
MISSED_DAILY_DECAY = 0.1


# ---------------------------------------------------------------------------
# PRD §3.1 default exhibition objection window.
# ---------------------------------------------------------------------------
DEFAULT_OBJECTION_WINDOW_HOURS = 72


# ---------------------------------------------------------------------------
# PRD §3.5 overnight inspection freshness window for COMPLETED.
# ---------------------------------------------------------------------------
OVERNIGHT_INSPECTION_FRESHNESS_HOURS = 8


# ---------------------------------------------------------------------------
# PRD §2.3 pagination defaults.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Seconds-conversion constants for /_clock/advance payloads.
# ---------------------------------------------------------------------------
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Test-helper defaults (NOT in PRD; convenience values for factories).
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # Default cell descriptors for a freshly created floor plan.
    "DEFAULT_POWER_KW_PER_CELL": 2.0,
    "DEFAULT_WATER_LPM_PER_CELL": 10.0,
    "DEFAULT_NETWORK_MBPS_PER_CELL": 100,
    "DEFAULT_GRID_ROWS": 5,
    "DEFAULT_GRID_COLS": 5,
    "DEFAULT_CAPACITY_MAX": 100,
}


__all__ = [
    "TIER_BASE_STANDARD_CENTS",
    "TIER_BASE_PREMIUM_CENTS",
    "TIER_BASE_ISLAND_CENTS",
    "ISLAND_OVERSIZE_PER_CELL_PCT",
    "ISLAND_OVERSIZE_CELL_THRESHOLD",
    "CORNER_MULTIPLIER",
    "THEME_ADDON_PREFIX",
    "THEME_ADDON_CENTS",
    "SENIORITY_CAP_YEARS",
    "SENIORITY_PER_YEAR",
    "SPONSOR_WEIGHT",
    "LOTTERY_DIVISOR",
    "LOTTERY_TOKEN_MAX",
    "WORK_ORDER_TAX_RATE",
    "CLEANING_DISCOUNT_RATE",
    "CLEANING_DISCOUNT_MULTIPLIER",
    "TICKET_BASE_VISITOR",
    "TICKET_BASE_PROFESSIONAL_BUYER",
    "TICKET_BASE_STUDENT",
    "TICKET_BASE_VIP",
    "ONSITE_SURCHARGE_MULTIPLIER",
    "GROUP_THRESHOLD",
    "GROUP_DISCOUNT_MULTIPLIER",
    "POSTURE_SATURATION_RATIO",
    "POSTURE_RECOVERY_RATIO",
    "MAKE_GOOD_TIER_BASE_CENTS",
    "MAKE_GOOD_FACTOR",
    "FULFILLED_SCORE",
    "MAKE_GOOD_BASE_SCORE",
    "MISSED_BASE_SCORE",
    "MISSED_DAILY_DECAY",
    "DEFAULT_OBJECTION_WINDOW_HOURS",
    "OVERNIGHT_INSPECTION_FRESHNESS_HOURS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "TEST_DEFAULTS",
]
