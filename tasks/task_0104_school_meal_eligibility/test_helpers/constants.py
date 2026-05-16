"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Federal Poverty Guideline table (cents/year by household_size) — PRD §3.4.
# PRD §3.4: "one person 15,000.00 dollars (1,500,000 cents), two people
# 20,300.00 dollars (2,030,000 cents), three people 25,600.00 dollars
# (2,560,000 cents), four people 30,900.00 dollars (3,090,000 cents),
# five people 36,200.00 dollars (3,620,000 cents), six people 41,500.00
# dollars (4,150,000 cents), seven people 46,800.00 dollars (4,680,000
# cents), and eight people 52,100.00 dollars (5,210,000 cents)."
# ---------------------------------------------------------------------------
FEDERAL_POVERTY_GUIDELINE_BY_SIZE = {
    1: 1_500_000,
    2: 2_030_000,
    3: 2_560_000,
    4: 3_090_000,
    5: 3_620_000,
    6: 4_150_000,
    7: 4_680_000,
    8: 5_210_000,
}


# ---------------------------------------------------------------------------
# FRL classification thresholds — PRD §3.4.
# PRD §3.4: "When the ratio is at most 1.30, the classifier returns FREE.
# When the ratio is greater than 1.30 but at most 1.85, the classifier
# returns REDUCED. Otherwise it returns DENIED_PAID."
# ---------------------------------------------------------------------------
FREE_THRESHOLD_RATIO: float = 1.30
REDUCED_THRESHOLD_RATIO: float = 1.85


# ---------------------------------------------------------------------------
# Reduced co-pay — PRD §3.6.
# PRD §3.6: "exactly 40 cents (the reduced co-pay) when tier_at_serving
# is REDUCED".
# ---------------------------------------------------------------------------
REDUCED_COPAY_CENTS: int = 40


# ---------------------------------------------------------------------------
# USDA reimbursement rates — PRD §3.6, §3.7.
# PRD §3.6: "480 cents when tier_at_serving is FREE, 420 cents when
# tier_at_serving is REDUCED, or 50 cents when tier_at_serving is PAID".
# ---------------------------------------------------------------------------
USDA_FREE_RATE_CENTS: int = 480
USDA_REDUCED_RATE_CENTS: int = 420
USDA_PAID_RATE_CENTS: int = 50


# ---------------------------------------------------------------------------
# High-sodium threshold — PRD §3.3.
# PRD §3.3: "The high-sodium flag is true when sodium_mg is at least 600
# milligrams, with the comparison non-strict — a value of exactly 600
# milligrams is flagged."
# ---------------------------------------------------------------------------
HIGH_SODIUM_THRESHOLD_MG: int = 600


# ---------------------------------------------------------------------------
# FrlApplication household-size bounds — PRD §3.4.
# PRD §3.4: "household_size (an integer from 1 through 8 inclusive —
# submissions outside this band are rejected with ERR_VALIDATION)".
# ---------------------------------------------------------------------------
HOUSEHOLD_SIZE_MIN: int = 1
HOUSEHOLD_SIZE_MAX: int = 8


# ---------------------------------------------------------------------------
# Student grade-level bounds — PRD §3.1.
# PRD §3.1: "grade_level is an integer from 0 through 12 inclusive (0
# representing kindergarten)".
# ---------------------------------------------------------------------------
GRADE_LEVEL_MIN: int = 0
GRADE_LEVEL_MAX: int = 12


# ---------------------------------------------------------------------------
# Auto-renewal income tolerance — PRD §3.5.
# PRD §3.5: "the new application's declared_annual_income_cents must
# differ from the prior application's declared_annual_income_cents by no
# more than five percent in either direction".
# ---------------------------------------------------------------------------
AUTO_RENEWAL_INCOME_TOLERANCE: float = 0.05


# ---------------------------------------------------------------------------
# Auto-renewal sentinel reviewer id — PRD §3.5.
# PRD §3.5: "its reviewer_user_id is set to the sentinel
# SYSTEM_AUTO_RENEW".
# ---------------------------------------------------------------------------
AUTO_RENEW_REVIEWER_ID: str = "SYSTEM_AUTO_RENEW"


# ---------------------------------------------------------------------------
# Allergen enumeration — PRD §3.2.
# PRD §3.2: "The allergen field is one of PEANUT, TREE_NUT, DAIRY, EGG,
# SOY, WHEAT, FISH, or SHELLFISH."
# ---------------------------------------------------------------------------
ALLERGENS = (
    "PEANUT",
    "TREE_NUT",
    "DAIRY",
    "EGG",
    "SOY",
    "WHEAT",
    "FISH",
    "SHELLFISH",
)

# PRD §3.2: "The severity field is one of MILD, MODERATE, or SEVERE."
SEVERITIES = ("MILD", "MODERATE", "SEVERE")


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — used when a test does not pin a specific value.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "DEFAULT_FULL_PRICE_CENTS": 350,
    "DEFAULT_CALORIES": 500,
    "DEFAULT_SODIUM_MG": 200,
    "DEFAULT_GRADE_LEVEL": 5,
    "DEFAULT_HOUSEHOLD_SIZE": 4,
    "DEFAULT_INCOME_FREE_CENTS": 2_000_000,        # ratio < 1.30
    "DEFAULT_INCOME_REDUCED_CENTS": 5_000_000,     # 1.30 < ratio <= 1.85
    "DEFAULT_INCOME_DENIED_CENTS": 8_000_000,      # ratio > 1.85
    "DEFAULT_SCHOOL_YEAR_START": "2026-08-01T00:00:00.000Z",
}


__all__ = [
    "FEDERAL_POVERTY_GUIDELINE_BY_SIZE",
    "FREE_THRESHOLD_RATIO",
    "REDUCED_THRESHOLD_RATIO",
    "REDUCED_COPAY_CENTS",
    "USDA_FREE_RATE_CENTS",
    "USDA_REDUCED_RATE_CENTS",
    "USDA_PAID_RATE_CENTS",
    "HIGH_SODIUM_THRESHOLD_MG",
    "HOUSEHOLD_SIZE_MIN",
    "HOUSEHOLD_SIZE_MAX",
    "GRADE_LEVEL_MIN",
    "GRADE_LEVEL_MAX",
    "AUTO_RENEWAL_INCOME_TOLERANCE",
    "AUTO_RENEW_REVIEWER_ID",
    "ALLERGENS",
    "SEVERITIES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
