"""Domain thresholds and constants.

Derived from PRD prose §2.9 (rent cap), §3.5 (notice window), §3.6
(cure windows), §3.1 (violation window), §2.3 (pagination).
"""
from __future__ import annotations


# PRD §2.9 — rent-increase caps
RENT_CAP_CA_BASE_PCT: float = 5.0
RENT_CAP_OR_BASE_PCT: float = 7.0
RENT_CAP_AZ_FLAT_PCT: float = 10.0
RENT_CAP_CEILING_PCT: float = 10.0


# PRD §3.5 — "effective_on must be at least 90 calendar days after the
# moment of issuance."
NOTICE_MIN_WINDOW_DAYS: int = 90


# PRD §3.6 — "The cure window is exactly 30 days for NONPAYMENT,
# exactly 14 days for RULE_VIOLATION, and zero days for ILLEGAL_USE."
CURE_WINDOW_DAYS_NONPAYMENT: int = 30
CURE_WINDOW_DAYS_RULE_VIOLATION: int = 14
CURE_WINDOW_DAYS_ILLEGAL_USE: int = 0


# PRD §3.1 — "the last 365 days"; boundary inclusive at 365, exclusive at 366.
VIOLATION_WINDOW_DAYS: int = 365


# PRD §2.3 — pagination defaults
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# Allowed state codes — PRD §2.9
STATE_CODES = ("CA", "FL", "OR", "AZ", "TX")
APPORTIONMENT_METHODS = ("SUB_METER", "EQUAL_SPLIT")
VIOLATION_TYPES = ("NONPAYMENT", "RULE_VIOLATION", "ILLEGAL_USE")


# Convenience defaults used by factories — tests can override anything.
TEST_DEFAULTS = {
    "park_name_prefix": "TestPark",
    "park_state_code": "CA",
    "park_master_cpi_pct": 2.00,
    "park_apportionment_method": "EQUAL_SPLIT",
    "park_anchor_day": 1,
    "lot_base_rent_cents": 100_000,
    "lot_sub_meter_reading_kwh": 0.0,
    "home_assessed_value_cents": 5_000_000,
    "resident_name_prefix": "TestResident",
    "rent_increase_proposed_cents": 110_000,
    "sale_price_cents": 6_000_000,
    "conversion_offer_cents": 5_000_000,
    "master_total_cents": 10_000,
}


__all__ = [
    "RENT_CAP_CA_BASE_PCT",
    "RENT_CAP_OR_BASE_PCT",
    "RENT_CAP_AZ_FLAT_PCT",
    "RENT_CAP_CEILING_PCT",
    "NOTICE_MIN_WINDOW_DAYS",
    "CURE_WINDOW_DAYS_NONPAYMENT",
    "CURE_WINDOW_DAYS_RULE_VIOLATION",
    "CURE_WINDOW_DAYS_ILLEGAL_USE",
    "VIOLATION_WINDOW_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "STATE_CODES",
    "APPORTIONMENT_METHODS",
    "VIOLATION_TYPES",
    "TEST_DEFAULTS",
]
