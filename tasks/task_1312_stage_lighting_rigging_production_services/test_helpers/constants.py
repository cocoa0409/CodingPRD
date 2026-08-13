"""Domain thresholds and numeric constants from the PRD's calculation rules (§3)."""

# Rigging load factors (PRD §3.3)
DYNAMIC_FACTOR = {"STRAIGHT": 1.10, "BRIDLE": 1.10, "DEAD_HANG": 1.00}
MOTOR_SELF_WEIGHT_KG = 20
BRIDLE_UNCERTAINTY = 1.15

# Power distribution sizing (PRD §3.4)
FEEDER_LOSS_PCT_PER_100M = 0.03
POWER_FACTOR = 0.9
DERATING = 0.8
VOLTAGE = 208
MAX_IMBALANCE_PCT = 0.15
GENERATOR_TIERS_KVA = [45, 60, 100, 150, 200, 300, 400]

# Crew labor (PRD §3.5)
MEAL_WINDOW_HOURS = 6
NON_UNION_ST_HOURS = 10
OT1_MULTIPLIER = 1.5
OT2_MULTIPLIER = 2.0
IATSE_MEAL_PENALTY_HOURS = 2

# Equipment rental billing tiers (PRD §3.6)
TIER1_DAYS = 3
TIER1_FACTOR = 1.0
TIER2_DAYS = 7
TIER2_FACTOR = 0.5
TIER3_FACTOR = 0.25

# Truck pack (PRD §3.6)
DUNNAGE_PCT = 0.02

# Damage valuation (PRD §3.8)
DEPRECIATION_PER_YEAR = 0.10
DEPRECIATION_FLOOR = 0.20
DIMINUTION_PCT = 0.15

# Venue labor-parameter defaults (PRD §3.1)
VENUE_DEFAULTS = {
    "min_call_hours": 4,
    "ot1_threshold_hours": 8,
    "ot2_threshold_hours": 12,
    "turnaround_min_hours": 8,
    "crew_call_publish_lead_hours": 48,
    "engineering_submission_lead_hours": 72,
}

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 10000,
    "DAILY_RATE_CENTS": 5000,
    "REPLACEMENT_COST_CENTS": 100000,
    "ACQUIRED_AT": "2024-08-01T00:00:00Z",
    "MAX_POINT_CAPACITY_KG": 500,
    "BAY_AGGREGATE_LIMIT_KG": 2000,
    "HOUSE_POWER_AMPS_PER_PHASE": 200,
    "DOCK_DOORS": 2,
}
