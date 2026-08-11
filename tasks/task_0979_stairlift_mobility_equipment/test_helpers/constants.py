"""Domain thresholds and pricing constants named in the PRD."""

THRESHOLDS = {
    # Quote pricing
    "LABOR_RATE_CENTS": 8500,                 # standard labor rate per install hour
    "RAIL_COST_PER_M_CENTS": 22000,           # rail materials per metre
    "CURVED_MULTIPLIER": 1.35,                # curved-stair rail cost multiplier
    "OUTDOOR_SEALING_CENTS": 45000,           # flat sealing surcharge for outdoor exposure
    "COMMITTED_RENTAL_MONTHS_DEFAULT": 6,     # nominal rental commitment in quote math
    "QUOTE_TTL_DAYS": 30,                     # platform quote time-to-live
    # Measurement ranges (millimetres)
    "STAIR_RISE_MIN_MM": 500,
    "STAIR_RISE_MAX_MM": 6000,
    "STAIR_RUN_MIN_MM": 500,
    "STAIR_RUN_MAX_MM": 12000,
    "STAIR_WIDTH_MIN_MM": 600,
    "STAIR_WIDTH_MAX_MM": 1500,
    "LANDING_CLEARANCE_MAX_MM": 3000,
    "LANDING_CLEARANCE_MIN_MM": 500,          # approval safety gate
    # Crews
    "INSTALL_BUFFER_MINUTES": 60,             # same-crew install buffer, both sides
    "REMOVAL_DAILY_CAPACITY": 2,              # removals per crew per UTC day
    # Service plans
    "TIER_BASE_CENTS": {"BASIC": 2900, "STANDARD": 4900, "PREMIUM": 7900},
    "TIER_CAP_CENTS": {"BASIC": 50000, "STANDARD": 150000, "PREMIUM": 400000},
    "RISK_ADDER_OUTDOOR_PCT": 0.15,
    "RISK_ADDER_CURVED_PCT": 0.20,
    "RISK_ADDER_REFURB_PCT": 0.10,
    "WAIVER_DISCOUNT": 0.85,
    "SERVICE_PLAN_DUE_DAYS": 180,
    "SERVICE_PLAN_LAPSE_OVERDUE_DAYS": 90,
    # Buyback
    "USEFUL_LIFE_MONTHS": 120,
    "MARKET_YEARLY_RETENTION": 0.85,
    "CONDITION_FACTOR": {"REFURB_A": 0.85, "REFURB_B": 0.65, "REFURB_C": 0.35,
                         "RETIRED": 0.0},
    "REGION_DEMAND_FACTOR": {"NORTH": 1.10, "SOUTH": 0.95, "EAST": 1.00, "WEST": 1.05},
    # Removal gates
    "PURCHASE_COOLING_OFF_DAYS": 30,
    "RENTAL_MIN_COMMITTED_MONTHS": 3,
    # Logical clock
    "CLOCK_START_ISO": "2026-05-01T00:00:00Z",
}

# Standard catalog models used across scenarios. Prices picked so that:
#  - straight assessment (2400x3200mm -> rail 4.00m) PURCHASE issued total == 502000
#  - curved assessment (2000x4100mm -> rail 4.56m) PURCHASE issued total == 636432
MODEL_STRAIGHT = {
    "model_code": "SL-STRAIGHT-100",
    "kind": "STAIRLIFT",
    "supports_curved": False,
    "supports_outdoor": False,
    "min_stair_width_mm": 700,
    "base_purchase_price_cents": 380000,
    "monthly_rental_rate_cents": 7500,
    "install_labor_hours": 4,
}

MODEL_CURVED = {
    "model_code": "SL-CURVED-200",
    "kind": "STAIRLIFT",
    "supports_curved": True,
    "supports_outdoor": False,
    "min_stair_width_mm": 700,
    "base_purchase_price_cents": 450000,
    "monthly_rental_rate_cents": 8500,
    "install_labor_hours": 6,
}

MODEL_CURVED_OUTDOOR = {
    "model_code": "SL-CURVED-200",
    "kind": "STAIRLIFT",
    "supports_curved": True,
    "supports_outdoor": True,
    "min_stair_width_mm": 700,
    "base_purchase_price_cents": 450000,
    "monthly_rental_rate_cents": 8500,
    "install_labor_hours": 6,
}

# Standard measurement sets (all within PRD ranges).
MEASURE_STRAIGHT = {
    "staircase_kind": "STRAIGHT",
    "stair_rise_mm": 2400,
    "stair_run_mm": 3200,
    "stair_width_mm": 800,
    "landing_clearance_mm": 600,
    "has_outdoor_exposure": False,
    "electrical_outlet_within_2m": True,
}
# rail length = 4.00 m

MEASURE_CURVED = {
    "staircase_kind": "CURVED",
    # PRD §3.1 geometry gate: for CURVED, stair_run_mm >= 2 * stair_rise_mm
    # (4100 >= 2*2000). sqrt(2000^2 + 4100^2) mm = 4.5618 m -> 4.56 m.
    "stair_rise_mm": 2000,
    "stair_run_mm": 4100,
    "stair_width_mm": 800,
    "landing_clearance_mm": 600,
    "has_outdoor_exposure": False,
    "electrical_outlet_within_2m": True,
}
# rail length = 4.56 m

MEASURE_CURVED_OUTDOOR = dict(MEASURE_CURVED, has_outdoor_exposure=True)

TEST_DEFAULTS = {
    "INSTALL_START": "2026-06-10T09:00:00Z",
    "INSTALL_END": "2026-06-10T13:00:00Z",
    "INSTALL_CLOCK": "2026-06-10T09:30:00Z",
    "BASE_CLOCK": "2026-06-01T00:00:00Z",
    "PAST_COOLING_OFF_CLOCK": "2026-07-15T00:00:00Z",
}
