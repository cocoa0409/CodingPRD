"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock's fixed starting instant (PRD §2.4).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# The instant every fixture pins the clock to unless a test moves it.
FIXTURE_CLOCK = "2026-08-05T08:00:00Z"
FIXTURE_DATE = "2026-08-05"

# Department optional-configuration defaults (PRD §3.1).
DEPARTMENT_DEFAULTS = {
    "target_margin_pct": 0.32,
    "shelf_life_days_ground": 2,
    "shelf_life_days_whole_muscle": 5,
    "shelf_life_days_vac_packed": 14,
    "max_safe_case_temp_c": 4.4,
    "critical_case_temp_c": 7.0,
    "pickup_slot_capacity": 2,
    "grind_sanitation_buffer_min": 30,
    "markdown_floor_pct": 0.10,
    "shrink_tolerance_pct": 0.015,
    "deposit_rate": 0.25,
}

# Per-facing capacity in pounds by merchandising class (PRD §3.6).
FACING_CAPACITY_LB = {
    "GROUND": 4,
    "WHOLE_MUSCLE": 6,
    "VAC_PACKED": 8,
}

THRESHOLDS = {
    # Pricing (PRD §3.4)
    "BOOK_SALABLE_YIELD": 0.62,
    "TIER_1_CEILING_CENTS": 800,
    "TIER_2_CEILING_CENTS": 1600,
    "TIER_1_BUMP": 0.0,
    "TIER_2_BUMP": 0.02,
    "TIER_3_BUMP": 0.04,
    "EFFECTIVE_MARGIN_CAP": 0.60,
    "REPRICE_THRESHOLD_PCT": 0.02,
    # Cutting test (PRD §3.2)
    "UNACCOUNTED_TOLERANCE_LB": 0.05,
    "REVISION_LIMIT": 2,
    # Case plan (PRD §3.6)
    "DEMAND_UPLIFT": 1.15,
    "CARRY_CAP_FACTOR": 0.3,
    "FILL_OVERAGE_CAP": 1.25,
    "POSTURE_RESTRICTED_HAIRCUT": 0.5,
    # Cold chain (PRD §3.7)
    "CONSECUTIVE_FAILURE_THRESHOLD": 2,
    "ESCALATION_MINUTES": 240,
    # Pre-orders (PRD §3.8)
    "AMEND_LIMIT": 2,
    "CANCELLATION_REFUND_SHARE": 0.5,
    # Trim (PRD §2.8)
    "REGRIND_GENERATION_LIMIT": 1,
}

# Canonical fixture literals — the shared vocabulary every composite fixture
# builds from, so the arithmetic asserted by the tests is reproducible.
TEST_DEFAULTS = {
    "DEPARTMENT_NAME": "Meat 41",
    "STORE_CODE": "S041",
    "SECOND_DEPARTMENT_NAME": "Meat 42",
    "SECOND_STORE_CODE": "S042",
    "VENDOR_NAME": "Prairie Packing",
    "P1_PRIMAL_CODE": "BEEF_RIBEYE_LIP_ON",
    "P1_GROSS_WEIGHT_LB": 100.0,
    "P1_RECEIVING_SHRINK_LB": 1.5,
    "P1_INVOICE_COST_CENTS": 84000,
    "P1_FREIGHT_COST_CENTS": 2500,
    "P1_VENDOR_ALLOWANCE_CENTS": 500,
    "P1_RECEIVED_AT": "2026-08-05T06:00:00Z",
    # P1 derivations (PRD §3.1): net 98.50 lb, landed 86000 cents, 873.0964 /lb
    "P1_NET_WEIGHT_LB": 98.50,
    "P1_LANDED_COST_TOTAL_CENTS": 86000,
    "P1_LANDED_COST_PER_LB_CENTS": 873.0964,
    "RIB01_ITEM_CODE": "RIB01",
    "RIB01_SUBPRIMAL_CODE": "RIBEYE_STEAK",
    "GRD80_ITEM_CODE": "GRD80",
    "GRD80_SUBPRIMAL_CODE": "GROUND_BEEF_80",
    "CUSTOMER_NAME": "R. Ruiz",
    "CUSTOMER_PHONE": "555-0100",
    "SECOND_CUSTOMER_NAME": "T. Okafor",
    "SECOND_CUSTOMER_PHONE": "555-0101",
}
