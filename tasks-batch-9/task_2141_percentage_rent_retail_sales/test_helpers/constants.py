"""Domain thresholds and the fixed values the workflow narratives name."""

# Exclusion capping (percentage caps in basis points of gross sales).
AGGREGATE_EXCLUSION_CAP_BPS = 1500

EXCLUSION_CAP_BPS = {
    "STANDARD": {
        "RETURNS_AND_ALLOWANCES": 1200,
        "SALES_TAX": 10000,
        "GIFT_CARD_ISSUANCE": 500,
        "INTERCOMPANY_TRANSFER": 10000,
        "EMPLOYEE_DISCOUNT": 300,
        "ONLINE_SHIP_FROM_STORE": 10000,
        "VENDING_AND_SERVICE": 200,
    },
    "RESTRICTIVE": {
        "RETURNS_AND_ALLOWANCES": 800,
        "SALES_TAX": 10000,
        "GIFT_CARD_ISSUANCE": 0,
        "INTERCOMPANY_TRANSFER": 10000,
        "EMPLOYEE_DISCOUNT": 100,
        "ONLINE_SHIP_FROM_STORE": 0,
        "VENDING_AND_SERVICE": 200,
    },
}

# Absolute ceilings that bind regardless of profile or gross sales.
EXCLUSION_HARD_CAP_CENTS = {
    "GIFT_CARD_ISSUANCE": 500_000,
    "EMPLOYEE_DISCOUNT": 250_000,
}

THRESHOLDS = {
    # Occupancy cost at or above this puts the lease on the watchlist.
    "OCR_WATCHLIST_BPS": 1500,
    # Estimate billings on a lease at or above this force the watchlist.
    "DELINQUENCY_STRIKE_LIMIT": 3,
    # Trailing periods forming the delinquency-estimate lookback window.
    "ESTIMATE_LOOKBACK_PERIODS": 3,
    # Ten percent uplift over the tenant's own trailing average.
    "ESTIMATE_UPLIFT_BPS": 11000,
    # Eighty percent of a pro-rata share of the breakpoint when no history exists.
    "ESTIMATE_NO_HISTORY_FACTOR_BPS": 8000,
    # Fallback relief rate when an alternative-sales-rent window is empty.
    "CO_TENANCY_DEFAULT_RELIEF_BPS": 5000,
    # Trailing accepted/adjusted reports feeding the alternative rent.
    "ALTERNATIVE_RENT_LOOKBACK_PERIODS": 3,
    # Whole days of separation required on each side of an audit window.
    "AUDIT_COOLDOWN_DAYS": 30,
    # Two full dispute-amend cycles are the contractual limit.
    "MAX_AMENDMENT_ROUNDS": 2,
}

# The logical clock's value before any caller sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "CENTER_NAME": "Northgate Commons",
    "CENTER_CODE": "NGC",
    "TOTAL_GLA_SQFT": 400_000,
    "ANCHOR_GLA_SQFT": 200_000,
    "TENANT_GLA_SQFT": 4_000,
    "ANCHOR_TENANT_GLA_SQFT": 120_000,
    "LEASED_SQFT": 4_000,
    "ANNUAL_BASE_RENT_CENTS": 12_000_000,
    "PERCENTAGE_RATE_BPS": 600,
    "ARTIFICIAL_BREAKPOINT_CENTS": 40_000_000,
    # A breakpoint no test sale can cross, used when a scenario must stay unbilled.
    "UNREACHABLE_BREAKPOINT_CENTS": 200_000_000,
    "REPORTING_DEADLINE_DAYS": 10,
    "YEAR_START": "2026-09-01T00:00:00Z",
    "YEAR_END": "2027-09-01T00:00:00Z",
    "CLOCK_AT_YEAR_START": "2026-09-01T00:00:00Z",
}

# A syntactically valid UUID that names no resource in any test's database.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

__all__ = [
    "AGGREGATE_EXCLUSION_CAP_BPS", "EXCLUSION_CAP_BPS",
    "EXCLUSION_HARD_CAP_CENTS", "THRESHOLDS", "DEFAULT_CLOCK_UTC",
    "TEST_DEFAULTS", "UNKNOWN_UUID",
]
