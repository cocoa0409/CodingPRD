"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Supervision / licensure — PRD §3.2.
# ---------------------------------------------------------------------------
# PRD §3.2: "the therapist must have accumulated at least 3000.00 hours
# in supervision_hours_accrued (the boundary is inclusive, so exactly
# 3000.00 qualifies)."
REQUIRED_HOURS_FOR_LICENSURE: float = 3000.00

# PRD §3.7: "its supervision_credit_hours is computed (1.00 for
# INDIVIDUAL, 1.50 for INTAKE)."
INDIVIDUAL_CREDIT_HOURS: float = 1.00
INTAKE_CREDIT_HOURS: float = 1.50


# ---------------------------------------------------------------------------
# Sliding-fee scale — PRD §3.4.
# ---------------------------------------------------------------------------
# PRD §3.4: per-household-size federal poverty level base amounts.
# "1,497,000 cents for a household of one, 2,044,000 cents for a
# household of two, 2,591,000 cents for a household of three, and
# 3,138,000 cents for a household of four. For households larger than
# four, the base is extended by adding 547,000 cents per additional
# person beyond four."
FPL_BASE_CENTS: dict = {
    1: 1_497_000,
    2: 2_044_000,
    3: 2_591_000,
    4: 3_138_000,
}
FPL_INCREMENT_CENTS_PER_PERSON_OVER_4: int = 547_000


def fpl_base_cents(household_size: int) -> int:
    """Return the PRD §3.4 FPL base in cents for `household_size`."""
    if household_size <= 4:
        return FPL_BASE_CENTS[household_size]
    return (
        FPL_BASE_CENTS[4]
        + (household_size - 4) * FPL_INCREMENT_CENTS_PER_PERSON_OVER_4
    )


# PRD §3.4 sliding-fee tier brackets and their resulting percent.
# "a ratio that is at most 1.00 yields sliding_fee_tier_pct of 20; a
# ratio that exceeds 1.00 but is at most 1.50 yields 40; a ratio that
# exceeds 1.50 but is at most 2.00 yields 60; a ratio that exceeds 2.00
# but is at most 2.50 yields 80; any ratio above 2.50 yields 100."
SLIDING_FEE_TIER_PERCENTAGES: tuple = (20, 40, 60, 80, 100)
SLIDING_FEE_TIER_UPPER_BOUNDS: tuple = (1.00, 1.50, 2.00, 2.50)


# ---------------------------------------------------------------------------
# Crisis assessment scoring — PRD §3.9.
# ---------------------------------------------------------------------------
# PRD §3.9: per-factor weights for crisis composite_score.
# "4.005 for the suicidal-ideation factor, 3.005 for the prior-attempts
# factor, 2.005 for the substance-use factor, 1.005 for the
# social-isolation factor, and 2.505 for the access-to-means factor."
CRISIS_WEIGHT_SI: float = 4.005
CRISIS_WEIGHT_PA: float = 3.005
CRISIS_WEIGHT_SU: float = 2.005
CRISIS_WEIGHT_SO: float = 1.005
CRISIS_WEIGHT_AM: float = 2.505

# PRD §3.9: risk-level bucketing thresholds (inclusive lower bounds).
# "a composite_score of at least 23.55 yields HIGH; a composite_score
# below 23.55 but at least 15.00 yields MODERATE; anything below 15.00
# yields LOW."
CRISIS_HIGH_THRESHOLD: float = 23.55
CRISIS_MODERATE_THRESHOLD: float = 15.00

# PRD §3.9: factor input ranges.
CRISIS_SI_MIN: int = 0
CRISIS_SI_MAX: int = 4
CRISIS_PA_MIN: int = 0
CRISIS_PA_MAX: int = 3
CRISIS_SU_MIN: int = 0
CRISIS_SU_MAX: int = 2
CRISIS_SO_MIN: int = 0
CRISIS_SO_MAX: int = 2
CRISIS_AM_MIN: int = 0
CRISIS_AM_MAX: int = 2


# ---------------------------------------------------------------------------
# Appointment scheduling / check-in — PRD §3.6.
# ---------------------------------------------------------------------------
# PRD §3.6: "The check-in is admitted only when the current clock is
# within the window [scheduled_start − 15min, scheduled_start + 30min]."
CHECKIN_WINDOW_EARLY_MINUTES: int = 15
CHECKIN_WINDOW_LATE_MINUTES: int = 30

# PRD §3.6: "The proposed window must also leave a minimum gap of five
# minutes from any existing appointment for the same patient ..."
PATIENT_MIN_GAP_MINUTES: int = 5


# ---------------------------------------------------------------------------
# Claim void window — PRD §3.8.
# ---------------------------------------------------------------------------
# PRD §3.8: "only when the owning session was completed within the last
# seven days as measured against the deterministic clock."
CLAIM_VOID_WINDOW_DAYS: int = 7


# ---------------------------------------------------------------------------
# PSYPACT — PRD §3.6.
# ---------------------------------------------------------------------------
# PRD §3.6: "The PSYPACT state set comprises AL, AR, AZ, CO, CT, DC, DE,
# FL, GA, IL, KS, KY, ME, MD, MN, NE, NV, NH, NJ, NC, OH, OK, PA, TN,
# TX, UT, VA, WA, WV, WI, WY."
PSYPACT_STATES: frozenset = frozenset({
    "AL", "AR", "AZ", "CO", "CT", "DC", "DE", "FL", "GA", "IL", "KS",
    "KY", "ME", "MD", "MN", "NE", "NV", "NH", "NJ", "NC", "OH", "OK",
    "PA", "TN", "TX", "UT", "VA", "WA", "WV", "WI", "WY",
})


# ---------------------------------------------------------------------------
# Crisis assessment authorisation lookback — PRD §3.9.
# ---------------------------------------------------------------------------
# PRD §3.9: "the acting therapist has had a CHECKED_IN or COMPLETED
# appointment with this patient at any time in the prior ninety days ..."
CRISIS_LOOKBACK_DAYS: int = 90


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10, with a minimum of 1 and a maximum of
# 100 ... offset defaults to 0 and must be a non-negative integer."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Field-format constants — PRD §3.1 / §3.4 / §3.6.
# ---------------------------------------------------------------------------
# PRD §3.1: "The npi is the National Provider Identifier, a ten-digit
# numeric string that must match the regular shape of ten digits ..."
NPI_REGEX: str = r"^[0-9]{10}$"

# PRD §3.1: "a state_code (the two-letter US state code, matching the
# regular shape of two uppercase letters) ..."
US_STATE_CODE_REGEX: str = r"^[A-Z]{2}$"


# ---------------------------------------------------------------------------
# Test defaults — convenient values used by fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # Clock anchor used by all time-sensitive setups.
    # PRD §2.8 establishes the test-driven monotonic clock.
    "CLOCK_ANCHOR": "2026-05-17T10:00:00.000Z",
    # Default rack rates (cents).
    "RACK_90791_CENTS": 20_000,
    "RACK_90834_CENTS": 15_000,
    # Default in-network plan allowed amounts (cents).
    "ALLOWED_90791_CENTS": 12_000,
    "ALLOWED_90834_CENTS": 9_550,
    # Default copay (cents).
    "COPAY_CENTS": 2_500,
    # A non-PSYPACT state used for cross-state failure setups.
    "NON_PSYPACT_STATE": "CA",
}


__all__ = [
    "REQUIRED_HOURS_FOR_LICENSURE",
    "INDIVIDUAL_CREDIT_HOURS",
    "INTAKE_CREDIT_HOURS",
    "FPL_BASE_CENTS",
    "FPL_INCREMENT_CENTS_PER_PERSON_OVER_4",
    "fpl_base_cents",
    "SLIDING_FEE_TIER_PERCENTAGES",
    "SLIDING_FEE_TIER_UPPER_BOUNDS",
    "CRISIS_WEIGHT_SI",
    "CRISIS_WEIGHT_PA",
    "CRISIS_WEIGHT_SU",
    "CRISIS_WEIGHT_SO",
    "CRISIS_WEIGHT_AM",
    "CRISIS_HIGH_THRESHOLD",
    "CRISIS_MODERATE_THRESHOLD",
    "CRISIS_SI_MIN",
    "CRISIS_SI_MAX",
    "CRISIS_PA_MIN",
    "CRISIS_PA_MAX",
    "CRISIS_SU_MIN",
    "CRISIS_SU_MAX",
    "CRISIS_SO_MIN",
    "CRISIS_SO_MAX",
    "CRISIS_AM_MIN",
    "CRISIS_AM_MAX",
    "CHECKIN_WINDOW_EARLY_MINUTES",
    "CHECKIN_WINDOW_LATE_MINUTES",
    "PATIENT_MIN_GAP_MINUTES",
    "CLAIM_VOID_WINDOW_DAYS",
    "PSYPACT_STATES",
    "CRISIS_LOOKBACK_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "NPI_REGEX",
    "US_STATE_CODE_REGEX",
    "TEST_DEFAULTS",
]
