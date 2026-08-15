"""Domain thresholds — documented shop-configuration defaults (PRD §2.10)."""

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Documented shop configuration defaults (PRD §2.10).
SHOP_DEFAULTS = {
    "labor_rate_cents_per_hour": 14500,
    "expedite_multiplier": 1.35,
    "emergency_multiplier": 1.75,
    "expedite_cutoff_hours": 48,
    "emergency_cutoff_hours": 24,
    "honing_pass_fee_cents": 4000,
    "cut_fee_cents": 1500,
    "kerf_mm": 3,
    "min_remnant_mm": 300,
    "default_chrome_rod_cost_per_mm_cents": 42,
    "default_honing_tube_cost_per_mm_cents": 65,
    "supplies_pct_of_labor": 0.04,
    "cleanliness_target_code4": 18,
    "cleanliness_target_code6": 16,
    "cleanliness_target_code14": 13,
    "quote_ttl_hours": 168,
    "bay_buffer_minutes": 30,
    "loyalty_silver_threshold_cents": 100000,
    "loyalty_gold_threshold_cents": 500000,
    "loyalty_silver_pct": 0.05,
    "loyalty_gold_pct": 0.10,
    "env_fee_pct": 0.02,
    "env_fee_min_cents": 500,
    "callout_base_cents": 25000,
    "emergency_callout_window_hours": 4,
    "emergency_callout_multiplier": 2.0,
    "mileage_free_km": 50,
    "mileage_rate_cents_per_km": 250,
    "crimp_fee_cents": 4500,
    "crimp_tolerance_mm": 0.3,
    "hose_price_wire_braid_2sn_cents_per_m": 3200,
    "hose_price_spiral_4sh_cents_per_m": 5700,
    "hose_price_thermoplastic_cents_per_m": 1800,
    "exchange_credit_cap_pct": 0.30,
    "core_disposal_fee_cents": 7500,
    "core_base_small_cents": 40000,
    "core_base_medium_cents": 90000,
    "core_base_large_cents": 160000,
    "core_bore_medium_max_mm": 100,
    "core_bore_large_max_mm": 200,
    "pressure_test_factor": 1.5,
    "test_hold_min_minutes": 10,
    "rated_pressure_class_3000_psi": 3000,
    "rated_pressure_class_5000_psi": 5000,
}

# A contamination sample that meets all three default ISO 4406 targets:
# c4=200000 -> code 18 (<=18), c6=60000 -> code 16 (<=16), c14=8000 -> code 13 (<=13).
CLEAN_SAMPLE = {"c4_count": 200000, "c6_count": 60000, "c14_count": 8000}

# Pressure-test pass parameters under shop defaults for a CLASS_3000 cylinder.
REQUIRED_HOLD_PSI_CLASS_3000 = 4500  # round_half_up(1.5 x 3000)
PASS_DURATION_MIN = 10

# Standard booking window for pressure tests (clock default is 2026-08-01).
DEFAULT_TEST_WINDOW = ("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
