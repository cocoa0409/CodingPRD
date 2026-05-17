"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Tier band — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "Tiers are integers from 1 (preferred generic) to 5
# (specialty / non-preferred)."
TIER_MIN: int = 1
TIER_MAX: int = 5

# PRD §3.4 / §3.5: tier 1 and 2 take a flat formulary copay; 3, 4, 5
# use coinsurance.
TIER_FLAT_COPAY_MAX: int = 2  # tiers 1 and 2 are "flat copay"


# ---------------------------------------------------------------------------
# Channel / days-supply bands — PRD §3.4 / §2.8 rung 10
# ---------------------------------------------------------------------------
# PRD §3.4: "RETAIL_30 permits a days_supply of 1 through 34 inclusive,
# MAIL_ORDER_90 permits 60 through 100 inclusive, and SPECIALTY permits
# 1 through 30 inclusive."
RETAIL_30_DAYS_SUPPLY_MIN: int = 1
RETAIL_30_DAYS_SUPPLY_MAX: int = 34
MAIL_ORDER_90_DAYS_SUPPLY_MIN: int = 60
MAIL_ORDER_90_DAYS_SUPPLY_MAX: int = 100
SPECIALTY_DAYS_SUPPLY_MIN: int = 1
SPECIALTY_DAYS_SUPPLY_MAX: int = 30

# PRD §3.4: "quantity must be at least 1."
QUANTITY_MIN: int = 1


# ---------------------------------------------------------------------------
# PA effective window — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "the approval writes effective_start to the current clock
# time, writes effective_end to the current clock time plus 180 days".
PA_EFFECTIVE_WINDOW_DAYS: int = 180
PA_EFFECTIVE_WINDOW_SECONDS: int = PA_EFFECTIVE_WINDOW_DAYS * 24 * 3600


# ---------------------------------------------------------------------------
# PA revision limit — PRD §3.3 / §2.8 rung 13
# ---------------------------------------------------------------------------
# PRD §3.3: "a fresh revision is only legal while revision_count is
# strictly less than 3 at the moment of resubmit (so 0, 1, and 2 are
# the only legal source values, yielding 1, 2, and 3 respectively
# after the increment)."
PA_REVISION_LIMIT: int = 3


# ---------------------------------------------------------------------------
# Rebate clawback window — PRD §3.6 / §3.7
# ---------------------------------------------------------------------------
# PRD §3.6: "clawback_window_days non-negative integer that defaults
# to 90 when omitted".
DEFAULT_CLAWBACK_WINDOW_DAYS: int = 90


# ---------------------------------------------------------------------------
# Mail-order discount — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "mail_order_discount_rate defaults to 0.90 when omitted
# from the creation payload."
DEFAULT_MAIL_ORDER_DISCOUNT_RATE: float = 0.90


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "if not provided, it defaults to 10, with a minimum of 1
# and a maximum of 100. The offset parameter specifies the number of
# items to skip and defaults to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------
SECONDS_PER_DAY: int = 86_400


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # Plan defaults sized to fit common test scenarios; tests override
    # for boundary work.
    "PLAN_DEDUCTIBLE_CENTS": 50_000,        # $500.00
    "PLAN_OOP_MAX_CENTS": 200_000,          # $2,000.00
    "PLAN_COINSURANCE_RATE": 0.20,          # 20 %
    "PLAN_MAIL_ORDER_DISCOUNT_RATE": DEFAULT_MAIL_ORDER_DISCOUNT_RATE,

    # Drug defaults.
    "DRUG_UNIT_ALLOWED_CENTS": 10_000,      # $100.00 per unit

    # FormularyEntry defaults.
    "FORMULARY_TIER": 3,                    # coinsurance branch
    "FORMULARY_COPAY_CENTS": 0,

    # Claim defaults.
    "CLAIM_DAYS_SUPPLY_RETAIL": 30,
    "CLAIM_DAYS_SUPPLY_MAIL": 90,
    "CLAIM_DAYS_SUPPLY_SPECIALTY": 30,
    "CLAIM_QUANTITY": 30,

    # Copay-card defaults.
    "COPAY_CARD_MAX_BENEFIT_CENTS": 5_000,
    "COPAY_CARD_PER_CLAIM_CAP_CENTS": 5_000,

    # Rebate-agreement defaults.
    "REBATE_RATE": 0.15,
    "REBATE_CLAWBACK_WINDOW_DAYS": DEFAULT_CLAWBACK_WINDOW_DAYS,

    # Default prescriber NPI used in PA factories (PRD §3.3 — exactly
    # 10 digits). Tests that need uniqueness override.
    "DEFAULT_PRESCRIBER_NPI": "1234567890",

    # Default member DOB.
    "DEFAULT_DATE_OF_BIRTH": "1985-04-12",
}


__all__ = [
    "TIER_MIN",
    "TIER_MAX",
    "TIER_FLAT_COPAY_MAX",
    "RETAIL_30_DAYS_SUPPLY_MIN",
    "RETAIL_30_DAYS_SUPPLY_MAX",
    "MAIL_ORDER_90_DAYS_SUPPLY_MIN",
    "MAIL_ORDER_90_DAYS_SUPPLY_MAX",
    "SPECIALTY_DAYS_SUPPLY_MIN",
    "SPECIALTY_DAYS_SUPPLY_MAX",
    "QUANTITY_MIN",
    "PA_EFFECTIVE_WINDOW_DAYS",
    "PA_EFFECTIVE_WINDOW_SECONDS",
    "PA_REVISION_LIMIT",
    "DEFAULT_CLAWBACK_WINDOW_DAYS",
    "DEFAULT_MAIL_ORDER_DISCOUNT_RATE",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SECONDS_PER_DAY",
    "TEST_DEFAULTS",
]
