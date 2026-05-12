"""Domain constants used across factories, fixtures, and tests.

All numeric thresholds come from PRD §3 (Business Logic & Workflows) and
§2 (Global Specifications). Keep PRD-exact: never invent intermediate
constants the PRD does not name.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Court fee constants — PRD §3.6 (court_fee tiered ladder)
# ---------------------------------------------------------------------------
CRIMINAL_FLAT_CENTS = 50_000   # PRD §3.6: "$500"
ADMIN_FLAT_CENTS = 30_000      # PRD §3.6: "$300"

# Tier ladder: (lower_cents_inclusive, upper_cents, rate_bps).
# CIVIL/ARBITRATION: "first 10,000 dollars (cents 0..1,000,000) at 5% (500 bps);
# slice 10,000..100,000 dollars (cents 1,000,000..10,000,000) at 3%;
# slice 100,000..1,000,000 dollars (cents 10,000,000..100,000,000) at 2%;
# any amount above one million dollars (cents above 100,000,000, up to a
# 9,999,999,999-cent ceiling) at 1%."
TIER_LADDER = [
    (0, 1_000_000, 500),
    (1_000_000, 10_000_000, 300),
    (10_000_000, 100_000_000, 200),
    (100_000_000, 9_999_999_999, 100),
]

ARBITRATION_DISCOUNT_NUMERATOR = 1
ARBITRATION_DISCOUNT_DENOMINATOR = 2  # 50% discount


# ---------------------------------------------------------------------------
# Time-entry / billing constants — PRD §3.6
# ---------------------------------------------------------------------------
MINUTES_PER_HOUR = 60
MAX_TIME_ENTRY_MINUTES = 1440         # PRD §3.6: ">0 and <=1440 (one day)"
MIN_TIME_ENTRY_MINUTES_EXCLUSIVE = 0  # PRD §3.6: "must be greater than 0"

CONTINGENT_RATE_BPS_MIN = 1
CONTINGENT_RATE_BPS_MAX = 5000        # PRD §3.6: "5000 representing the firm's hard 50% cap"

REBUTTAL_GROUND_MIN_LEN = 1           # PRD §3.5: "between 1 and 500 characters"
REBUTTAL_GROUND_MAX_LEN = 500


# ---------------------------------------------------------------------------
# Hearing constants — PRD §2.7, §3.4
# ---------------------------------------------------------------------------
TRAVEL_BUFFER_MINUTES = 30            # PRD §2.7: "30-minute travel buffer"
RESTRICTED_HEARING_WINDOW_HOURS = 24  # PRD §2.8: "in the next 24 hours"


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Party contact constraints — PRD §3.2
# ---------------------------------------------------------------------------
CONTACT_PHONE_MIN_LEN = 7
CONTACT_PHONE_MAX_LEN = 20


# ---------------------------------------------------------------------------
# Case archive — PRD §2.9
# ---------------------------------------------------------------------------
CASE_ARCHIVE_DAYS = 30                # "After a case has been closed for at least 30 days"


# ---------------------------------------------------------------------------
# Default test values
# ---------------------------------------------------------------------------
DEFAULT_HOURLY_RATE_CENTS = 30_000        # $300/hour, partner default
DEFAULT_JUNIOR_RATE_CENTS = 10_000        # $100/hour
DEFAULT_SENIOR_RATE_CENTS = 20_000        # $200/hour
DEFAULT_CIVIL_CLAIM_CENTS = 5_000_000     # $50k — straddles bracket1/bracket2 for tier tests
DEFAULT_ARBITRATION_CLAIM_CENTS = 5_000_000


# Case-type → case-number TYPE_CODE mapping (PRD §3.1).
CASE_NUMBER_TYPE_CODES = {
    "CIVIL": "CIV",
    "CRIMINAL": "CRM",
    "ADMINISTRATIVE": "ADM",
    "ARBITRATION": "ARB",
}


__all__ = [
    "CRIMINAL_FLAT_CENTS",
    "ADMIN_FLAT_CENTS",
    "TIER_LADDER",
    "ARBITRATION_DISCOUNT_NUMERATOR",
    "ARBITRATION_DISCOUNT_DENOMINATOR",
    "MINUTES_PER_HOUR",
    "MAX_TIME_ENTRY_MINUTES",
    "MIN_TIME_ENTRY_MINUTES_EXCLUSIVE",
    "CONTINGENT_RATE_BPS_MIN",
    "CONTINGENT_RATE_BPS_MAX",
    "REBUTTAL_GROUND_MIN_LEN",
    "REBUTTAL_GROUND_MAX_LEN",
    "TRAVEL_BUFFER_MINUTES",
    "RESTRICTED_HEARING_WINDOW_HOURS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "CONTACT_PHONE_MIN_LEN",
    "CONTACT_PHONE_MAX_LEN",
    "CASE_ARCHIVE_DAYS",
    "DEFAULT_HOURLY_RATE_CENTS",
    "DEFAULT_JUNIOR_RATE_CENTS",
    "DEFAULT_SENIOR_RATE_CENTS",
    "DEFAULT_CIVIL_CLAIM_CENTS",
    "DEFAULT_ARBITRATION_CLAIM_CENTS",
    "CASE_NUMBER_TYPE_CODES",
]
