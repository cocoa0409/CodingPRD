"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Pasteurization completion threshold (PRD §3.1): hours at target temp.
    "MIN_HOURS_AT_TARGET": 6.0,
    # Settlement tolerance / tiers (PRD §3.6).
    "SHORTFALL_TOLERANCE_PCT": 0.05,
    "TIER1_MAX_RATIO": 0.15,
    "TIER1_RATE_CENTS_PER_KG": 120,
    "TIER2_MAX_RATIO": 0.40,
    "TIER2_RATE_CENTS_PER_KG": 200,
    "TIER3_RATE_CENTS_PER_KG": 350,
    # Spent substrate accounting (PRD §3.8).
    "SPENT_YIELD_FACTOR": 0.75,
    "TIPPING_FEE_CENTS_PER_TONNE": 2500,
    "FLOOR_PRICE_CENTS_PER_TONNE": 1500,
    # Piece-pay grade factors (PRD §3.4).
    "GRADE_A_FACTOR": 1.20,
    "GRADE_B_FACTOR": 1.00,
    "CULL_FACTOR": 0.0,
    # Contamination severity gate (PRD §3.7).
    "QUARANTINE_SEVERITY": 4,
    # Turnover buffer appended to room window blocking intervals (PRD §3.2).
    "ROOM_TURNOVER_BUFFER_DAYS": 2,
}

# The canonical White Button variety used by most farm-chain fixtures.
WB1_VARIETY = {
    "variety_code": "WB1",
    "display_name": "White Button",
    "substrate_recipe": "PHASE_II_COMPOST",
    "target_bioefficiency_pct": 25.0,
    "shelf_life_days": 5,
    "spawn_run_days": 3,
    "casing_days": 2,
    "max_flushes": 3,
    "flush_yield_distribution": [0.5, 0.3, 0.2],
}

# Server startup value of the logical clock (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "BATCH_TONNAGE": 40.0,
    "SPAWN_KG": 280.0,
    "ROOM_CAPACITY_TONNES": 50.0,
    "TUNNEL_CAPACITY_TONNES": 100.0,
    "ALLOCATED_TONNAGE": 40.0,
    "WORKER_RATE_CENTS_PER_KG": 50,
    "CYCLE_PLANNED_START": "2026-05-03T00:00:00Z",
    "CYCLE_PLANNED_END": "2026-06-14T00:00:00Z",
    "PASTEURIZATION_WINDOW_START": "2026-05-01T00:00:00Z",
    "PASTEURIZATION_WINDOW_END": "2026-05-02T00:00:00Z",
    "LINE_COMMITTED_KG": 500.0,
    "LINE_WEEK_START": "2026-05-04T00:00:00Z",
    "LINE_WEEK_END": "2026-05-10T00:00:00Z",
}
