"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim PRD sentence in the docstring
of the test that references it.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Charge calculation — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "a BRIEF consult is 5000 cents, a STANDARD consult is 10000
# cents, and an EXTENDED consult is 18000 cents."
BRIEF_CHARGE_CENTS: int = 5000
STANDARD_CHARGE_CENTS: int = 10000
EXTENDED_CHARGE_CENTS: int = 18000

# PRD §3.7: "the platform applies a courtesy discount of fifteen percent
# (1500 basis points)".
SELF_PAY_DISCOUNT_BPS: int = 1500


# ---------------------------------------------------------------------------
# Follow-up windows — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "When the maximum schedule is II, due_by is set to the
# current clock time plus 30 days."
SCHEDULE_II_WINDOW_DAYS: int = 30

# PRD §3.7: "When the maximum schedule is III, IV, or V (and no II
# prescription is present), due_by is the current clock time plus 60
# days."
SCHEDULE_III_TO_V_WINDOW_DAYS: int = 60

# PRD §3.7: "Otherwise — when no qualifying controlled-substance
# prescription exists, or all qualifying prescriptions have dea_schedule
# NONE — due_by is the current clock time plus 90 days."
NON_CONTROLLED_WINDOW_DAYS: int = 90


# ---------------------------------------------------------------------------
# Prescription compliance score — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "The first leg awards 40 points when the consult's
# routing_basis is FULL_LICENSE, 30 points when it is IMLC_EXPEDITED".
SCORE_FULL_LICENSE: int = 40
SCORE_IMLC_EXPEDITED: int = 30

# PRD §3.5: "The second leg awards 30 points when dea_schedule is NONE,
# and 30 points when dea_schedule is anything other than NONE and the
# issuing physician's dea_number is present and the prescription's
# epcs_two_factor_token is present".
SCORE_DEA_OK: int = 30

# PRD §3.5 — refill compliance leg, schedule-dependent.
SCORE_REFILL_OK: int = 20
SCORE_REFILL_PARTIAL: int = 10

# PRD §3.5 — days-supply leg.
SCORE_DAYS_LE_30: int = 10
SCORE_DAYS_LE_60: int = 5

# PRD §3.5: "Issuance requires the score to be at least 80".
COMPLIANCE_SCORE_MIN_PASS: int = 80


# ---------------------------------------------------------------------------
# Prescription field ranges — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "The days_supply must lie between 1 and 90 inclusive, and
# refills must lie between 0 and 11 inclusive".
DAYS_SUPPLY_MIN: int = 1
DAYS_SUPPLY_MAX: int = 90
REFILLS_MIN: int = 0
REFILLS_MAX: int = 11


# ---------------------------------------------------------------------------
# Patient insurance coinsurance — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "a coinsurance percentage stored as basis points
# (insurance_coinsurance_bps, where 2000 means twenty percent, with the
# constraint that the value is at least 0 and at most 10000)".
COINSURANCE_BPS_MIN: int = 0
COINSURANCE_BPS_MAX: int = 10000


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter defaults to 10 when omitted, must be at
# least 1, and must not exceed 100; the offset parameter defaults to 0
# when omitted and must be a non-negative integer."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §2.9 — clock anchor used by time-sensitive tests so deadlines
    # are deterministic.
    "CLOCK_ANCHOR": "2026-05-16T00:00:00.000Z",
    # Default license lifetime — generous so it stays ACTIVE through all
    # untimed tests.
    "DEFAULT_LICENSE_ISSUED_AT": "2025-01-01T00:00:00.000Z",
    "DEFAULT_LICENSE_EXPIRES_AT": "2030-01-01T00:00:00.000Z",
    # Default state code used by setups that do not exercise multi-state.
    "DEFAULT_STATE_CODE": "CA",
}


__all__ = [
    "BRIEF_CHARGE_CENTS",
    "STANDARD_CHARGE_CENTS",
    "EXTENDED_CHARGE_CENTS",
    "SELF_PAY_DISCOUNT_BPS",
    "SCHEDULE_II_WINDOW_DAYS",
    "SCHEDULE_III_TO_V_WINDOW_DAYS",
    "NON_CONTROLLED_WINDOW_DAYS",
    "SCORE_FULL_LICENSE",
    "SCORE_IMLC_EXPEDITED",
    "SCORE_DEA_OK",
    "SCORE_REFILL_OK",
    "SCORE_REFILL_PARTIAL",
    "SCORE_DAYS_LE_30",
    "SCORE_DAYS_LE_60",
    "COMPLIANCE_SCORE_MIN_PASS",
    "DAYS_SUPPLY_MIN",
    "DAYS_SUPPLY_MAX",
    "REFILLS_MIN",
    "REFILLS_MAX",
    "COINSURANCE_BPS_MIN",
    "COINSURANCE_BPS_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
