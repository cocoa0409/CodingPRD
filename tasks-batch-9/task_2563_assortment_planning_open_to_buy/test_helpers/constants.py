"""Numeric constants the PRD pins for the open-to-buy arithmetic, plus the
canonical planning scenario the fixtures build."""

# Seasonal receipt budget (PRD 3.4)
ROLE_RECEIPT_MULTIPLIER_BPS = {
    "TRAFFIC_DRIVER": 11000,
    "DESTINATION": 10000,
    "CONVENIENCE": 9000,
    "SEASONAL": 12500,
    "OCCASIONAL": 8500,
}
DEPARTMENT_SHARE_CAP_BPS = 1200
TURN_TARGET_REFERENCE_X100 = 300
TURN_FLOOR_X100 = 200

# Markdown reserve bands (PRD 3.4)
RESERVE_TIER_LOW_BPS = 4000
RESERVE_TIER_MID_BPS = 6500
RESERVE_TIER_HIGH_BPS = 8500
RESERVE_RATE_DEEP_BPS = 900
RESERVE_RATE_MID_BPS = 600
RESERVE_RATE_LIGHT_BPS = 350
RESERVE_RATE_MIN_BPS = 150

# Option slot capacity (PRD 3.4)
TIER_BREADTH_SHARE_BPS = {"GOOD": 4500, "BETTER": 3500, "BEST": 2000}
MIN_SLOTS_PER_TIER = 2

# Sell-through forecast (PRD 3.5)
TIER_BENCHMARK_BPS = {"GOOD": 6200, "BETTER": 5500, "BEST": 4300}
SELL_THROUGH_CAP_BPS = 9800

# Overlay multiplier clamp (PRD 3.5)
OVERLAY_MULTIPLIER_FLOOR_BPS = 5000
OVERLAY_MULTIPLIER_CEILING_BPS = 15000
OVERLAY_SEPARATION_BUFFER_DAYS = 7

# Posture bands (PRD 3.4)
POSTURE_OPEN_FLOOR_BPS = 1500
POSTURE_RESTRICTED_FLOOR_BPS = 500

# Variance verdict boundaries (PRD 3.7)
VARIANCE_BREACH_UNDER_BPS = -1000
VARIANCE_WATCH_UNDER_BPS = -400
VARIANCE_BREACH_OVER_BPS = 1500
WEEKS_PER_FISCAL_MONTH = 4

# Chase allocation (PRD 3.8)
CHASE_WINDOW_DAYS = 14
REFORECAST_ROUND_CAP = 3

# Logical clock (PRD 2.6)
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ─── Canonical planning scenario ──────────────────────
# Department WAPP -> Category DRSS (DESTINATION) -> StoreCluster Cold-A,
# Vendor Aurora Mills; CategoryPlan SPRING 2027 with months M1/M2 and one
# BETTER option plan. The derived numbers this scenario produces are pinned
# below so tests can assert them without recomputing.
CANONICAL = {
    "department": {
        "name": "Womens Apparel",
        "code": "WAPP",
        "fiscal_year": 2027,
        "sales_target_cents": 500_000_000,
        "margin_target_bps": 5600,
        "turn_target_x100": 320,
    },
    "category": {
        "name": "Dresses",
        "code": "DRSS",
        "role": "DESTINATION",
        "sales_share_bps": 3000,
    },
    "store_cluster": {
        "name": "Cold-A",
        "climate_zone": "COLD",
        "demographic_index_bps": 10500,
        "volume_tier": "A",
        "store_count": 40,
        "sales_index_bps": 11500,
    },
    "vendor": {
        "name": "Aurora Mills",
        "code": "AURM",
        "lead_time_days": 45,
        "weekly_unit_capacity": 12000,
        "min_order_units": 200,
        "cancel_cutoff_days": 21,
    },
    "max_open_units": 40000,
    "category_plan": {
        "season_code": "SPRING",
        "fiscal_year": 2027,
        "planned_sales_cents": 150_000_000,
        "planned_margin_bps": 5500,
        "planned_turn_x100": 320,
    },
    "month_1": {
        "month_index": 1,
        "fiscal_month_label": "2027-03",
        "first_receipt_date": "2027-03-05T00:00:00Z",
        "bom_inventory_cents": 20_000_000,
        "planned_sales_cents": 30_000_000,
        "planned_markdown_cents": 2_000_000,
        "planned_eom_cents": 22_000_000,
    },
    "month_2": {
        "month_index": 2,
        "fiscal_month_label": "2027-04",
        "first_receipt_date": "2027-04-02T00:00:00Z",
        "bom_inventory_cents": 22_000_000,
        "planned_sales_cents": 36_000_000,
        "planned_markdown_cents": 3_000_000,
        "planned_eom_cents": 24_000_000,
    },
    "option_plan": {
        "tier": "BETTER",
        "breadth_target": 14,
        "depth_units_per_option": 6,
        "assumed_unit_cost_cents": 2400,
    },
}

# Five-cell balanced size curve used by the canonical option plan.
CANONICAL_SIZE_CURVE = [
    {"size_label": "XS", "size_sort_order": 1, "pct_bps": 800},
    {"size_label": "S", "size_sort_order": 2, "pct_bps": 2200},
    {"size_label": "M", "size_sort_order": 3, "pct_bps": 3400},
    {"size_label": "L", "size_sort_order": 4, "pct_bps": 2600},
    {"size_label": "XL", "size_sort_order": 5, "pct_bps": 1000},
]

# Derived figures the canonical scenario yields once approved.
CANONICAL_RECEIPT_BUDGET_CENTS = 60_000_000
CANONICAL_M1_OTB_PLANNED_CENTS = 18_200_000
CANONICAL_M2_OTB_PLANNED_CENTS = 21_970_000
CANONICAL_OPTION_SLOTS_TOTAL = 14
CANONICAL_TARGET_UNITS_PER_OPTION = 276

# Operator identifiers. The four planning roles are opaque principals; a
# VendorRep's identifier is the id of its own Vendor row.
ADMIN_USER_ID = "ops-admin-1"
PLANNER_USER_ID = "planner-1"
DIRECTOR_USER_ID = "director-1"
BUYER_USER_ID = "buyer-1"
SECOND_PLANNER_USER_ID = "planner-2"
SECOND_DIRECTOR_USER_ID = "director-2"
