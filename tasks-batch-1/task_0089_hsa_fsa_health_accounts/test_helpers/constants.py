"""Domain thresholds — numeric constants from PRD calculations and the standard plan-year caps."""

# Age at which the HSA catch-up allowance applies (PRD §3.3).
CATCHUP_AGE = 55

# The standard plan-year cap schedule reused across the design recipes.
# These are the cap values the test scenarios assume; a plan year created with
# DEFAULT_PLAN_YEAR_CAPS yields exactly these limits.
DEFAULT_PLAN_YEAR_CAPS = {
    "hsa_individual_cap_cents": 437500,
    "hsa_family_cap_cents": 865000,
    "hsa_catchup_cents": 100000,
    "health_fsa_cap_cents": 335000,
    "dcfsa_cap_joint_cents": 500000,
    "dcfsa_cap_separate_cents": 250000,
}

# Convenience individual cap constants for boundary tests.
HSA_INDIVIDUAL_CAP_CENTS = 437500
HSA_FAMILY_CAP_CENTS = 865000
HSA_CATCHUP_CENTS = 100000
HEALTH_FSA_CAP_CENTS = 335000
DCFSA_CAP_JOINT_CENTS = 500000
DCFSA_CAP_SEPARATE_CENTS = 250000

# Standard coverage window used by most scenarios (PY2026).
DEFAULT_COVERAGE_START = "2026-01-01"
DEFAULT_COVERAGE_END = "2026-12-31"
DEFAULT_RUN_OUT_END = "2027-03-31"

# A clock instant inside the standard coverage window, used so claims file timely.
DEFAULT_CLOCK_IN_WINDOW = "2026-06-01T00:00:00Z"
# A clock instant past the standard filing deadline, used so settlement is reachable.
DEFAULT_CLOCK_PAST_DEADLINE = "2027-04-01T00:00:00Z"
