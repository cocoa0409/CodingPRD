"""Domain thresholds and numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Force-out band defaults (PRD §3.1)
    "DEFAULT_CASH_OUT_THRESHOLD_CENTS": 100000,
    "DEFAULT_ROLLOVER_THRESHOLD_CENTS": 700000,
    # Withholding (PRD §3.5)
    "FED_WITHHOLDING_RATE": 0.20,
    "STATE_WITHHOLDING_RATE_MAX": 0.15,
    # Notice window (PRD §3.4)
    "NOTICE_WINDOW_DAYS": 30,
    # Fee (PRD §3.6)
    "ANNUAL_FEE_CENTS": 6000,
    # Match scoring (PRD §3.7)
    "MATCH_W_SSN": 0.55,
    "MATCH_W_NAME": 0.30,
    "MATCH_W_DOB": 0.15,
    "MATCH_AUTO_CONFIRM": 0.850,
    "MATCH_CONFIRM_FLOOR": 0.650,
    "MATCH_REVIEW_FLOOR": 0.400,
    "MATCH_EXPIRE_DAYS": 90,
    # Stale/escheat (PRD §3.8)
    "CHECK_STALE_DAYS": 180,
    "ESCHEAT_WARNING_LEAD_DAYS": 90,
    "ESCHEAT_DORMANCY_DAYS": 1095,
}

TEST_DEFAULTS = {
    # Canonical logical-clock startup instant (PRD §2.4)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    "CLOCK_START_MS": "2026-08-01T00:00:00.000Z",
    # Notice deadline at default clock: 2026-08-01 + 30 days = 2026-08-31
    "DEADLINE_DEFAULT_MS": "2026-08-31T00:00:00.000Z",
    "DEADLINE_DEFAULT": "2026-08-31T00:00:00Z",
    "AFTER_DEADLINE": "2026-08-31T00:00:01Z",
    # Standard participant addresses
    "ADDR_LINE1": "1 Main St",
    "ADDR_CITY": "Springfield",
    "ADDR_STATE": "IL",
    "ADDR_ZIP": "62701",
}
