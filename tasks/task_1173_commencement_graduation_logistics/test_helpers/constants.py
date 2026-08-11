"""Domain thresholds and numeric constants from the PRD (§2.8, §3.2, §3.4, §3.6, §3.8)."""

THRESHOLDS = {
    # Honor GPA tier ladder (PRD §3.2), inclusive boundaries
    "SUMMA_THRESHOLD": 3.900,
    "MAGNA_THRESHOLD": 3.700,
    "CUM_THRESHOLD": 3.500,
    "GPA_DECIMALS": 3,
    # Regalia pricing tiers (PRD §3.4)
    "TIER1_MIN_CENTS": 10000,
    "TIER1_PCT": 0.10,
    "TIER2_MIN_CENTS": 20000,
    "TIER2_PCT": 0.15,
    "LATE_RATE": 0.10,
    # Conduct policy (PRD §3.6)
    "MAX_UNEXCUSED_STRIKES": 2,
    # Vendor cancellation fee (PRD §3.8)
    "CANCEL_BEFORE_START_PCT": 0.10,
    "CANCEL_AT_OR_AFTER_START_PCT": 0.50,
    # Seating sweep (PRD §3.5)
    "SEATS_PER_ROW": 4,
    "DEFAULT_SECTION": "A",
    # Temporal windows (PRD §2.10)
    "APPEAL_WINDOW_DAYS": 14,
    "CORRECTION_WINDOW_DAYS": 30,
}

# Waterfall ordering ranks (PRD §3.3): honor rank descending
HONOR_RANK = {
    "NONE": 0,
    "CUM_LAUDE": 1,
    "MAGNA_CUM_LAUDE": 2,
    "SUMMA_CUM_LAUDE": 3,
}

TEST_DEFAULTS = {
    # Logical clock fixed default before any client call (PRD §2.10)
    "CLOCK_DEFAULT": "2026-05-01T00:00:00Z",
    # Standard ceremony fixture deadlines used across scenarios
    "CEREMONY_DATE": "2026-06-01T15:00:00Z",
    "REGALIA_ORDER_DEADLINE": "2026-05-10T00:00:00Z",
    "TICKET_REQUEST_DEADLINE": "2026-05-15T00:00:00Z",
    "PRONUNCIATION_DEADLINE": "2026-05-20T00:00:00Z",
    "GUEST_TICKET_BASE_CAP": 4,
    "HONOR_BONUS_TICKETS": 2,
    "TICKET_RATIO": 1.0,
    "VENUE_CAPACITY": 10,
    "VENUE_ACCESSIBLE": 2,
}

# GPA ledgers (gpa_credits, quality_points) landing on pinned tiers after
# round-half-up to 3 decimals (PRD §2.8, §3.2)
GPA_LEDGERS = {
    "SUMMA": {"institutional_gpa_credits": 45, "institutional_quality_points": 175.5},   # 3.900
    "MAGNA": {"institutional_gpa_credits": 45, "institutional_quality_points": 170.0},   # 3.778
    "CUM": {"institutional_gpa_credits": 45, "institutional_quality_points": 162.0},     # 3.600
    "NONE": {"institutional_gpa_credits": 45, "institutional_quality_points": 153.0},    # 3.400
}
