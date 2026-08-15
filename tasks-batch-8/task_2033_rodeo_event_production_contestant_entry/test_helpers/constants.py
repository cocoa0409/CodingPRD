"""Domain thresholds — numeric constants from PRD calculations (§2.4, §2.6, §3)."""

THRESHOLDS = {
    # Flat sanction fee withheld from every entry charge (PRD §3.2).
    "SANCTION_FLAT_CENTS": 600,
    # Committee retention percentage of the gross fee, rounded half-up per
    # entry (PRD §3.2).
    "RETENTION_PCT": 0.12,
    # Share of the purse conceptually reserved for the average (PRD §3.7).
    "AVERAGE_SHARE_PCT": 0.30,
    # Welfare out limit; reaching it retires the animal (PRD §3.3).
    "MAX_OUTS_PER_RODEO": 3,
    # Judge travel buffer applied on both sides of a performance (PRD §3.4).
    "JUDGE_BUFFER_MINUTES": 45,
    # Minimum gross entry fee (PRD §3.1).
    "MIN_ENTRY_FEE_CENTS": 1000,
}

TEST_DEFAULTS = {
    # Logical clock reads exactly this instant at server startup (PRD §2.4).
    "CLOCK_START_ISO": "2026-08-01T00:00:00Z",
    # Default entry deadline used by fixtures — after the startup clock.
    "ENTRIES_CLOSE_AT": "2026-08-10T00:00:00Z",
    # Default performance window (a Friday evening).
    "PERF_STARTS_AT": "2026-08-14T19:00:00Z",
    "PERF_ENDS_AT": "2026-08-14T22:00:00Z",
    # Standard money amounts used across scenarios.
    "ENTRY_FEE_CENTS": 2000,
    "ADDED_MONEY_CENTS": 0,
    "DAY_RATE_CENTS": 10000,
    "PER_OUT_FEE_CENTS": 2000,
    "ARENA_CAPACITY": 300,
    "TICKET_UNIT_PRICE_CENTS": 2500,
}

# Derived per-entry split for the standard 2000-cent fee (PRD §3.2):
# retention round_half_up(2000 x 0.12) = 240; sanction 600; contribution 1160.
FEE_2000_SPLIT = {
    "committee_retention_cents": 240,
    "sanction_fee_cents": 600,
    "purse_contribution_cents": 1160,
}
