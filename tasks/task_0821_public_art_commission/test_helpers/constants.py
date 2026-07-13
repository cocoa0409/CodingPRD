"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Percent-for-art rate bounds (PRD §3.1).
DEFAULT_PERCENT_RATE = 0.01
MIN_PERCENT_RATE = 0.005
MAX_PERCENT_RATE = 0.05

# Panel composite score weights and gates (PRD §3.4).
W_ART = 0.40
W_FEAS = 0.25
W_COMM = 0.20
W_DUR = 0.15
DURABILITY_FLOOR = 40
TRIM_MIN = 3

# Loan interval buffer in calendar days (PRD §3.7).
LOAN_BUFFER_DAYS = 30

# Logical clock startup default (PRD §2.8).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Convenience defaults for setup.
TEST_DEFAULTS = {
    "CONSTRUCTION_BUDGET": 200000000,
    "PERCENT_RATE": 0.01,
    "DEADLINE": "2026-06-01T00:00:00Z",
}
