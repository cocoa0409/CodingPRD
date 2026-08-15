"""Domain thresholds and canonical fixture values (PRD §2.5, §2.6, §3)."""

# PRD §2.6 / §3.8: two thousand pounds per billable ton; scrap credit capped
# at five percent of the base amount.
TON_LBS = 2000
SCRAP_CREDIT_CAP_PCT = 0.05

# PRD §3.5: thirty-minute turnaround gap between runs sharing a work center.
TURNAROUND_MINUTES = 30

# PRD §2.5: the logical clock starts at exactly 2026-08-01T00:00:00Z.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Canonical alloy profile used by the happy-path fixtures: AISI-4140 with a
# [2100, 2300]F forge window, reheat limit 2, flash allowance 12.0%,
# 3 strokes per part, flow stress 8.0 ksi, chemistry maxima C 0.43 / Mn 1.10,
# grain-flow minimum 5, macro-etch PASS mandatory.
ALLOY_4140 = {
    "grade_code": "AISI-4140",
    "name": "CrMo Steel",
    "forge_temp_min_f": 2100,
    "forge_temp_max_f": 2300,
    "reheat_limit": 2,
    "flash_allowance_pct": 12.0,
    "strokes_per_part": 3,
    "flow_stress_ksi": 8.0,
    "carbon_max_pct": 0.43,
    "manganese_max_pct": 1.10,
    "grain_flow_min_rating": 5,
    "macro_etch_required": True,
}

# Canonical surcharge index: 250000 cents/ton + 10% energy for 2026-08.
SURCHARGE_4140_2026_08 = {
    "effective_month": "2026-08",
    "surcharge_cents_per_ton": 250000,
    "energy_pct": 0.10,
}

# Canonical work-order commercial envelope: average-rate tiers
# 1.0 t @ 2000000 c/t, 5.0 t @ 1800000 c/t, above at 1500000 c/t,
# scrap recovery 150 cents per accepted flash pound.
WORK_ORDER_DEFAULTS = {
    "customer_name": "Acme Aero",
    "part_number": "PN-100",
    "ordered_qty": 10,
    "part_net_weight_lbs": 40.00,
    "billet_weight_lbs": 50.00,
    "projected_area_in2": 25.0,
    "required_process": "PRESS",
    "price_tier1_limit_tons": 1.0,
    "price_tier1_cents_per_ton": 2000000,
    "price_tier2_limit_tons": 5.0,
    "price_tier2_cents_per_ton": 1800000,
    "price_tier3_cents_per_ton": 1500000,
    "scrap_recovery_rate_cents_per_lb": 150,
}

# Canonical heat: 20000.00 lbs received at 2.50 lbs/in (a 20.0 in cut is 50.00 lbs).
HEAT_DEFAULTS = {
    "mill_name": "Ellwood Bar Mill",
    "received_weight_lbs": 20000.00,
    "bar_lbs_per_in": 2.50,
}

FURNACE_DEFAULT_CAPACITY_LBS = 5000
DEFAULT_CHARGE_TEMP_F = 2200
DEFAULT_SOAK_MINUTES = 60

# Distinct user ids needed where segregation of duties compares recorded
# operator/submitter strings against the caller (PRD §2.1, §3.7).
USER_PLANT_MANAGER = "pm-1"
USER_SAW_OPERATOR = "saw-1"
USER_FURNACE_OPERATOR = "furn-1"
USER_FORGE_OPERATOR_1 = "op-1"
USER_DIE_TECH = "die-1"
USER_QUALITY_ENGINEER_1 = "qe-1"
USER_QUALITY_ENGINEER_2 = "qe-2"
USER_SALES_PLANNER = "sp-1"
