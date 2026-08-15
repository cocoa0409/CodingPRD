"""Domain thresholds and canonical tariff/unit parameters from the PRD.

All numeric constants cited by the PRD's calculation rules (§3) live here.
"""

# Per-commodity pounds-per-bushel constants (PRD §2.6).
LBS_PER_BUSHEL = {"CORN": 56, "SOYBEAN": 60, "WHEAT": 60}

# Commodity benchmark prices in cents per bushel (PRD §3.8).
BENCHMARK_PRICE_CENTS = {"CORN": 450, "SOYBEAN": 1050, "WHEAT": 620}

THRESHOLDS = {
    # Added to the water shrink to form the provisional shrink percentage.
    "HANDLING_SHRINK_PCT": 0.5,
    # Dryer safety limit on certified intake moisture (PRD §3.4 / §3.5).
    "DRYER_SAFETY_LIMIT_PCT": 26.0,
    # Liability ladder pre-existing condition thresholds (PRD §3.8).
    "PREEXISTING_MOISTURE_PCT": 26.0,
    "PREEXISTING_FM_PCT": 8.0,
    "OUT_OF_SPEC_TOLERANCE_PCT": 0.5,
    # Liability deductible and cap (PRD §3.8).
    "CLAIM_DEDUCTIBLE_CENTS": 2500,
    "CLAIM_CAP_PCT": 0.40,
    # A ticket preempted this many times can no longer requeue (PRD §3.4).
    "MAX_PREEMPTIONS": 2,
    # Lot target moisture bounds (PRD §3.2).
    "TARGET_MOISTURE_MIN": 10.0,
    "TARGET_MOISTURE_MAX": 20.0,
}

# Canonical CORN tariff window reused by most scenarios.
CANONICAL_SCHEDULE = {
    "commodity": "CORN",
    "effective_from": "2026-08-01",
    "effective_to": "2026-12-31",
    "t1_max_moisture_pct": 20.0,
    "t2_max_moisture_pct": 25.0,
    "rate_t1_cents_per_pt_bu": 4,
    "rate_t2_cents_per_pt_bu": 5,
    "rate_t3_cents_per_pt_bu": 7,
    "fm_threshold_pct": 3.0,
    "fm_surcharge_pct": 0.10,
    "min_charge_cents": 1500,
    "energy_t1_limit_therms": 60,
    "energy_t1_rate_cents_per_therm": 85,
    "energy_t2_rate_cents_per_therm": 95,
    "est_therms_per_hour": 12.5,
    "est_point_factor": 0.05,
}

# Canonical dryer unit capacity policy reused by most scenarios.
CANONICAL_UNIT = {
    "unit_code": "DRYER-1",
    "daily_capacity_bushels": 10000,
    "standard_class_cap_bushels": 8000,
    "throughput_bu_per_hour": 600,
    "cooldown_minutes": 30,
}

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 500000,
    "GROSS_WEIGHT_LBS": 44000,
    "TARE_WEIGHT_LBS": 34000,
    "TARGET_MOISTURE_PCT": 15.0,
    # Logical-clock position most scenarios start from.
    "CLOCK_2026_09_01": "2026-09-01T08:00:00Z",
    # Common drying window: 2026-09-05 08:00 -> 12:00 (4.0 hours).
    "RUN_DATE": "2026-09-05",
    "RUN_START": "2026-09-05T08:00:00Z",
    "RUN_END": "2026-09-05T12:00:00Z",
}
