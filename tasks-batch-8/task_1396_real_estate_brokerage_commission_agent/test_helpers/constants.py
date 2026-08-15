"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

THRESHOLDS = {
    # 1099 filing bar (PRD §3.9): $600 == 60000 cents, inclusive
    "FILING_THRESHOLD_CENTS": 60000,
    # P1 royalty cap and tier threshold used across the design indices
    "P1_ROYALTY_CAP_CENTS": 300000,
    "P1_TIER0_THRESHOLD_CENTS": 2500000,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK_ISO": "2026-08-01T00:00:00Z",
    "AGENT_JOIN_DATE": "2025-09-01",
}
