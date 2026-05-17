"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Contribution caps — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "For an HSA with self-only coverage, contribution_cap_cents
# is set to 412,500 cents ($4,125.00)."
HSA_CAP_SELF_ONLY_CENTS: int = 412_500

# PRD §3.2: "For an HSA with family coverage, it is 830,000 cents
# ($8,300.00)."
HSA_CAP_FAMILY_CENTS: int = 830_000

# PRD §3.2: "The HSA catch-up cap catch_up_cap_cents is 100,000 cents
# ($1,000.00) if, on December 31 of the plan year's calendar_year ...
# the account holder's age ... is at least 55".
HSA_CATCH_UP_CENTS: int = 100_000

# PRD §3.2: "the account holder's age ... is at least 55".
HSA_CATCH_UP_AGE: int = 55

# PRD §3.2: "For a Health FSA, contribution_cap_cents is set to 320,000
# cents ($3,200.00), and catch_up_cap_cents is 0."
HEALTH_FSA_CAP_CENTS: int = 320_000

# PRD §3.2: "For a Dependent Care FSA, contribution_cap_cents is set to
# ... 500,000 cents ($5,000.00) for every other filing status."
DCFSA_CAP_FAMILY_CENTS: int = 500_000

# PRD §3.2: "For a Dependent Care FSA, contribution_cap_cents is set to
# 250,000 cents ($2,500.00) when the linked account holder's
# tax_filing_status is MARRIED_SEPARATE".
DCFSA_CAP_MARRIED_SEPARATE_CENTS: int = 250_000


# ---------------------------------------------------------------------------
# Carryover ceiling — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "the amount carried forward is the lesser of the leftover
# and the carryover ceiling of 64,000 cents ($640.00)".
CARRYOVER_CAP_CENTS: int = 64_000


# ---------------------------------------------------------------------------
# HSA non-qualified distribution penalty — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "a penalty cents value is computed as the absolute value of
# the event's cents_delta multiplied by the HSA penalty rate of 2,000
# basis points (i.e., 20.00%) divided by 10,000".
HSA_PENALTY_RATE_BPS: int = 2_000


# ---------------------------------------------------------------------------
# SSN — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "ssn_last4, which must be exactly four numeric digits".
SSN_LAST4_LENGTH: int = 4


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10, with a minimum of 1 and a maximum
# of 100".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Grace period boundary — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "grace_period_end_date is set to March 15 of calendar_year+1
# at the instant YYYY-03-15T00:00:00Z".
GRACE_PERIOD_END_MONTH: int = 3
GRACE_PERIOD_END_DAY: int = 15


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "HSA_CAP_SELF_ONLY_CENTS": HSA_CAP_SELF_ONLY_CENTS,
    "HSA_CAP_FAMILY_CENTS": HSA_CAP_FAMILY_CENTS,
    "HEALTH_FSA_CAP_CENTS": HEALTH_FSA_CAP_CENTS,
    "DCFSA_CAP_FAMILY_CENTS": DCFSA_CAP_FAMILY_CENTS,
    "CARRYOVER_CAP_CENTS": CARRYOVER_CAP_CENTS,
}


__all__ = [
    "HSA_CAP_SELF_ONLY_CENTS",
    "HSA_CAP_FAMILY_CENTS",
    "HSA_CATCH_UP_CENTS",
    "HSA_CATCH_UP_AGE",
    "HEALTH_FSA_CAP_CENTS",
    "DCFSA_CAP_FAMILY_CENTS",
    "DCFSA_CAP_MARRIED_SEPARATE_CENTS",
    "CARRYOVER_CAP_CENTS",
    "HSA_PENALTY_RATE_BPS",
    "SSN_LAST4_LENGTH",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "GRACE_PERIOD_END_MONTH",
    "GRACE_PERIOD_END_DAY",
    "TEST_DEFAULTS",
]
