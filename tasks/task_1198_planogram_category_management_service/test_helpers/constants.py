"""Domain thresholds — numeric constants from PRD calculations."""

# Days-of-supply thresholds (PRD §3.4)
THRESHOLDS = {
    "DOS_UNDERSTOCK_DAYS": 3.0,
    "DOS_OVERSTOCK_DAYS": 21.0,
    "DOS_ZERO_DEMAND_SENTINEL": 9999.0,
    "SPACE_TO_SALES_INDEXED_SENTINEL": 999.0,
    "DEFAULT_COMPLIANCE_THRESHOLD_PCT": 85,
    "COMPLIANCE_WARN_BELOW_THRESHOLD": 10,
    "FAIL_RESET_PROJECT_WINDOW_DAYS": 14,
    "DEFAULT_CREW_MAX_CONCURRENT_PROJECTS": 1,
}

# Default logical clock at server startup (PRD §2.9)
CLOCK_START_ISO = "2026-05-01T00:00:00Z"
