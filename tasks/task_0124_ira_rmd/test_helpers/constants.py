"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Contribution caps — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The base regular cap is 7,000 dollars (700,000 cents)."
REGULAR_CAP_CENTS: int = 700_000

# PRD §3.3: "A catch-up addition of 1,000 dollars (100,000 cents) is
# granted when the participant's age on December 31 of the clock year is
# at least 50".
CATCHUP_CAP_CENTS: int = 100_000

# PRD §3.3: "the participant must independently be at least 50 years old
# on December 31 of the clock year".
CATCHUP_AGE: int = 50

# PRD §3.3: "at most 1,000,000 cents per single call".
MAX_SINGLE_CONTRIBUTION_CENTS: int = 1_000_000


# ---------------------------------------------------------------------------
# RMD — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "SECURE Act 2.0 sets the RMD age at 73."
RMD_AGE: int = 73

# PRD §3.5: "The table covers (at minimum) ages 73 through 78 with the
# following divisors: 26.5 at age 73, 25.5 at age 74, 24.6 at age 75,
# 23.7 at age 76, 22.9 at age 77, and 22.0 at age 78."
UNIFORM_LIFETIME_TABLE: dict = {
    73: 26.5,
    74: 25.5,
    75: 24.6,
    76: 23.7,
    77: 22.9,
    78: 22.0,
}

# PRD §3.5: "The Single Life Table provides (at minimum) the following
# anchor values: 45.7 at age 40, 41.0 at age 45, 36.2 at age 50, 31.6 at
# age 55, 27.1 at age 60, 22.9 at age 65, and 18.8 at age 70."
SINGLE_LIFE_TABLE: dict = {
    40: 45.7,
    45: 41.0,
    50: 36.2,
    55: 31.6,
    60: 27.1,
    65: 22.9,
    70: 18.8,
}


# ---------------------------------------------------------------------------
# Federal withholding — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the mandatory normal rate of 10%".
MANDATORY_NORMAL_RATE: float = 0.10

# PRD §3.4: "the mandatory RMD rate of 10% applies".
MANDATORY_RMD_RATE: float = 0.10

# PRD §3.4: "an additional 10% early adder, for a combined rate of 20%".
EARLY_ADDER: float = 0.10

# PRD §3.4: "when the participant is strictly younger than 59 in the
# clock year".
EARLY_PENALTY_AGE: int = 59


# ---------------------------------------------------------------------------
# Excess contribution penalty — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "the penalty is 6% of the excess rounded half-up to whole
# cents".
EXCESS_PENALTY_RATE: float = 0.06


# ---------------------------------------------------------------------------
# SECURE Act 10-year drain — PRD §3.2, §3.5
# ---------------------------------------------------------------------------
# PRD §3.2: "the SECURE Act ten-year drain window applies".
SECURE_DRAIN_YEARS: int = 10

# PRD §3.5: "an ExcessPenalty is issued whose ... penalty_amount_cents
# equals 25% of that residual balance (SECURE Act 25% excise)".
SECURE_FORFEIT_RATE: float = 0.25


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter defaults to 10, with a minimum of 1 and
# a maximum of 100. The offset parameter defaults to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Participant validation — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a non-empty string of 1 to 120 characters after trimming
# whitespace".
FULL_NAME_MIN_LEN: int = 1
FULL_NAME_MAX_LEN: int = 120

# PRD §3.1: "which must place the participant at age 18 or older on the
# day of creation".
MIN_PARTICIPANT_AGE_YEARS: int = 18


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "REGULAR_CAP_CENTS": REGULAR_CAP_CENTS,
    "CATCHUP_CAP_CENTS": CATCHUP_CAP_CENTS,
    "RMD_BALANCE_TEN_THOUSAND_DOLLARS": 1_000_000,
    "RMD_BALANCE_HUNDRED_THOUSAND_DOLLARS": 10_000_000,
}


__all__ = [
    "REGULAR_CAP_CENTS",
    "CATCHUP_CAP_CENTS",
    "CATCHUP_AGE",
    "MAX_SINGLE_CONTRIBUTION_CENTS",
    "RMD_AGE",
    "UNIFORM_LIFETIME_TABLE",
    "SINGLE_LIFE_TABLE",
    "MANDATORY_NORMAL_RATE",
    "MANDATORY_RMD_RATE",
    "EARLY_ADDER",
    "EARLY_PENALTY_AGE",
    "EXCESS_PENALTY_RATE",
    "SECURE_DRAIN_YEARS",
    "SECURE_FORFEIT_RATE",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "FULL_NAME_MIN_LEN",
    "FULL_NAME_MAX_LEN",
    "MIN_PARTICIPANT_AGE_YEARS",
    "TEST_DEFAULTS",
]
