"""Domain thresholds and default configuration values (PRD §2.7, §3.1, §3.4, §3.8)."""

THRESHOLDS = {
    # Supermajority tally: approval needs 3*A >= 2*(A+D) (PRD §3.4).
    "SUPERMAJORITY_RATIO_NUM": 2,
    "SUPERMAJORITY_RATIO_DEN": 3,
    # Escalation multipliers are basis points; 10000 bp == 1.0x (PRD §2.7).
    "BP_DENOMINATOR": 10000,
}

TEST_DEFAULTS = {
    # Association charter defaults used by most scenarios (PRD §3.1).
    "STATUTORY_RESPONSE_DAYS": 30,
    "COUNTING_MODE": "CALENDAR",
    "FINE_MODE": "SIMPLE_DAILY",
    "BASE_FINE_CENTS": 10000,
    "DAILY_FINE_CENTS": 1000,
    "LIEN_THRESHOLD_CENTS": 1000000,
    "COMMITTEE_SIZE": 5,
    "QUORUM_MIN": 3,
    "MAX_WINDOW_DAYS": 180,
    # Default requested construction window (half-open [start, end), PRD §2.8).
    "WINDOW_START": "2026-06-01",
    "WINDOW_END": "2026-07-15",
    # Logical clock instant used by time-sensitive scenarios (PRD §2.6).
    "EPOCH": "2026-05-01T09:00:00Z",
}
