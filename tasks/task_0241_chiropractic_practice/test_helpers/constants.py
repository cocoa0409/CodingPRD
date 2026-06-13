"""Domain thresholds — numeric constants from the PRD's calculations and rules.

NON_EXISTENT_UUID comes from the framework (re-exported via the barrel).
"""

# No-show fee tiers (PRD §3.8): strikes 1-2 -> 2500, 3-4 -> 5000, 5+ -> 7500;
# LATE_CANCEL is charged the base fee times the 0.5 multiplier.
NO_SHOW_FEE = {
    "FIRST_TIER_MAX_STRIKES": 2,
    "SECOND_TIER_MAX_STRIKES": 4,
    "FIRST_TIER_FEE_CENTS": 2500,
    "SECOND_TIER_FEE_CENTS": 5000,
    "THIRD_TIER_FEE_CENTS": 7500,
    "LATE_CANCEL_MULTIPLIER": 0.5,
}

# Practice-wide thresholds (PRD §2.7, §3.2, §3.4, §3.7).
THRESHOLDS = {
    "DISMISSAL_STRIKE_THRESHOLD": 5,    # §3.2/§3.7: 5 strikes => DISMISSED
    "LATE_CANCEL_WINDOW_HOURS": 24,     # §3.7: late-cancel window
    "REGRESSION_SEVERITY_THRESHOLD": 6, # §3.4: re-exam severity needed to regress
}

# Cap-counting visit types (PRD §3.6): only these consume an insurance cap slot.
CAP_COUNTING_VISIT_TYPES = ["ADJUSTMENT", "THERAPY", "RE_EXAM"]

# Convenience defaults used across fixtures/tests (not PRD-mandated values).
TEST_DEFAULTS = {
    "CASH_RATE_CENTS": 6000,
    "BILLED_AMOUNT_CENTS": 9000,
    "DURATION_MINUTES": 15,
    "NPI": "1234567890",
    "LICENSE_STATE": "CA",
    "DOB": "1980-01-01",
}
