"""Domain constants and shared test defaults for the membership/admission API.

Numeric values mirror the PRD's documented defaults and the canonical figures
used throughout the test suite. Generic NON_EXISTENT_UUID comes from the framework.
"""

# A well-formed UUID that resolves to no resource (for ERR_NOT_FOUND probes).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# Grace window length added to expires_at on ACTIVE -> GRACE (PRD §3.3: "plus thirty days").
GRACE_WINDOW_DAYS = 30

# Plan default term length (PRD §3.1: term_days "defaults to 365").
DEFAULT_TERM_DAYS = 365

# Canonical money figures reused across fixtures and tests (all integer cents).
TEST_DEFAULTS = {
    "ANNUAL_FEE_CENTS": 12000,
    "REINSTATEMENT_FEE_CENTS": 3000,
    "MEMBER_ADMISSION_CENTS": 1500,
    "NON_MEMBER_ADMISSION_CENTS": 2500,
    "SURCHARGE_CENTS": 1000,
    "GUEST_PASSES_GRANTED": 2,
    "HOUSEHOLD_MAX": 3,
}

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}
