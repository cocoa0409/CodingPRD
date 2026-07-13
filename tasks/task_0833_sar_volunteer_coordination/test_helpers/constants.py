"""Domain thresholds — numeric constants from the PRD calculations (§2.9, §3)."""

# Reimbursement tiered schedule (§3.8)
THRESHOLDS = {
    "MILEAGE_TIER1_LIMIT_MI": 50,
    "MILEAGE_RATE_TIER1_CPM": 65,
    "MILEAGE_RATE_TIER2_CPM": 40,
    "MEAL_PER_DIEM_CENTS": 1500,
    "MEAL_MAX_COUNT": 6,
    "LODGING_RATE_CENTS": 9000,
    # Coverage (§3.3)
    "COVERAGE_RATE_SQKM_PER_HOUR": 0.5,
    # Unit conversion (§2.9)
    "MI_PER_KM": 0.621371,
    # Member rest buffer for double-book on deploy (§3.4)
    "MEMBER_REST_BUFFER_MIN": 60,
}

# Logical clock startup default (§2.4)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "OPERATIONAL_PERIOD_HOURS": 12,
    "MAX_RESPONDERS": 8,
}
