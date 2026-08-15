"""Domain thresholds and shared test defaults (PRD §2.3, §3)."""

TEST_DEFAULTS = {
    # Standard eligibility window covering all of 2026 (PRD §3.2).
    "ELIGIBILITY_START": "2026-01-01",
    "ELIGIBILITY_END": "2026-12-31",
    # Standard pharmacy debt tolerance used by most scenarios (PRD §2.8).
    "AUTO_SUSPEND_THRESHOLD_CENTS": 5000,
    # Standard full-year audit window (PRD §3.8).
    "AUDIT_WINDOW_START": "2026-01-01",
    "AUDIT_WINDOW_END": "2026-12-31",
}

PAGINATION_DEFAULTS = {
    "LIMIT": 10,
    "OFFSET": 0,
    "MAX_LIMIT": 100,
}
