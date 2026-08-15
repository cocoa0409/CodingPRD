"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Certification passing score, inclusive (PRD §3.2)
    "PASS_SCORE": 80,
    # Current certification season (PRD §3.2)
    "CURRENT_SEASON": 2026,
    # Provisional intake estimate (PRD §3.4): flat 15% capped at $6,000
    "EITC_EST_CAP_CENTS": 600000,
    # Final determination tiers (PRD §3.5): (rate, cap_cents) by child count
    "FINAL_TIER_0_CAP_CENTS": 60000,
    "FINAL_TIER_1_CAP_CENTS": 400000,
    "FINAL_TIER_2_CAP_CENTS": 650000,
    # Savings-match incentive cap $100 (PRD §3.6)
    "MATCH_CAP_CENTS": 10000,
    # Maximum transmissions before rework closes (PRD §3.7)
    "MAX_SUBMISSIONS": 3,
    # Rejection follow-up due window in days (PRD §3.7)
    "FOLLOW_UP_DUE_DAYS": 5,
    # Appointment duration bounds in minutes (PRD §3.3)
    "MIN_DURATION_MINUTES": 15,
    "MAX_DURATION_MINUTES": 120,
    # Allocation cardinality ceiling (PRD §3.6)
    "MAX_ALLOCATIONS": 3,
}

# The startup logical clock (PRD §2.5)
STARTUP_CLOCK = "2026-08-01T00:00:00Z"
