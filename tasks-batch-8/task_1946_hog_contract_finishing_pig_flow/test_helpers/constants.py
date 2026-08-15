"""Domain thresholds and shared fixture terms (PRD §2.9, §3.2–§3.9)."""

THRESHOLDS = {
    # Square feet of floor space required per pig (PRD §3.2).
    "SQFT_PER_HEAD": 8,
    # Truck-wash validity window in hours (PRD §2.10, §3.5).
    "WASH_VALIDITY_HOURS": 48,
    # Barn downtime after a verified wash, in hours (PRD §3.6).
    "BARN_DOWNTIME_HOURS": 72,
    # Feed-delivery variance branch: >= 80% of quantity is DELIVERED (PRD §3.3).
    "FEED_DELIVERED_RATIO": 0.80,
    # Reject penalty per head shipped, in cents (PRD §3.5).
    "REJECT_PENALTY_CENTS_PER_HEAD": 1500,
    # FieldTech approval authority ceiling, in cents (PRD §2.6, §3.7).
    "FIELDTECH_APPROVE_LIMIT_CENTS": 50000,
    # Projected daily gain used in booking validation and preview (PRD §3.5, §3.8).
    "ADG_PROJECTION_LBS_PER_DAY": 1.85,
    # Projected feed-conversion ratio used in the settlement preview (PRD §3.8).
    "PROJ_FCR": 2.70,
    # Phase-plan allotment percentages (PRD §3.3).
    "PHASE_PLAN_PCT": {
        "STARTER": 0.15,
        "GROWER": 0.30,
        "FINISHER_1": 0.30,
        "FINISHER_2": 0.25,
    },
    # Land-application season: Mar 1 through Nov 30 of the plan year (PRD §3.9).
    "APPLICATION_WINDOW_START_MONTH_DAY": "03-01",
    "APPLICATION_WINDOW_END_MONTH_DAY": "11-30",
}

# Shared contract terms used across fixtures (per-head money in cents).
CONTRACT_TERMS = {
    "base_pay_cents_per_head": 4000,
    "bonus_cap_cents_per_head": 1200,
    "fcr_target": 2.60,
    "adg_target_lbs": 1.90,
    "mortality_threshold_pct": 5.00,
    "feed_budget_lbs_per_head": 650,
    "structural_owner_pct": 100,
    "equipment_owner_pct": 50,
    "routine_owner_pct": 0,
    "effective_date": "2026-01-01",
    "expiry_date": "2026-12-31",
}

# Default geometry for test barns.
DEFAULT_BARN = {
    "capacity_head": 1200,
    "floor_space_sqft": 9600,
}

# Default group shape: 500 head @ 50.0 lbs, 2026-03-02 placement, 2026-07-13 target.
DEFAULT_GROUP = {
    "placement_date": "2026-03-02",
    "target_market_date": "2026-07-13",
    "head_placed": 500,
    "avg_start_weight_lbs": 50.0,
}

TEST_DEFAULTS = {
    "STATE_CODE": "IA",
    "COUNTY": "Sioux",
    "PLANT_CODE": "P1",
    # The logical clock starts here before any operator sets it (PRD §2.4).
    "CLOCK_START": "2026-08-01T00:00:00Z",
}
