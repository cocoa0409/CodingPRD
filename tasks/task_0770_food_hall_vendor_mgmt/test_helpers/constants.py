"""Domain thresholds and default values from the PRD calculations (§3)."""

# Inspection hygiene-score result bands (PRD §3.3).
INSPECTION_PASS_MIN = 85          # score >= 85 -> PASS
INSPECTION_CONDITIONAL_MIN = 70   # 70 <= score < 85 -> CONDITIONAL; below 70 -> FAIL

# Compliance-grade weighting and letter bands (PRD §3.4).
WEIGHTS_1 = [1.0]
WEIGHTS_2 = [0.6, 0.4]            # newest, oldest
WEIGHTS_3 = [0.5, 0.3, 0.2]      # newest .. oldest
GRADE_BANDS = {"A": 90, "B": 80, "C": 70, "D": 60}  # else "F"

# Food-hall inter-event buffer default (PRD §3.1).
DEFAULT_EVENT_BUFFER_MINUTES = 60

# Standard lease commercial terms reused across settlement scenarios (PRD §3.2/§3.8).
TEST_DEFAULTS = {
    "BASE_RENT_CENTS": 200000,
    "PERCENTAGE_RATE": 0.08,
    "NATURAL_BREAKPOINT_CENTS": 5000000,
    "RENT_CAP_CENTS": 100000000,
    "SECURITY_DEPOSIT_CENTS": 100000,
    "LEASE_START_DATE": "2026-06-01",
    "LEASE_END_DATE": "2026-12-31",
}
