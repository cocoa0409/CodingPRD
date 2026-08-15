"""Domain thresholds and price schedules from the PRD (§2.8–§2.11, §3.4, §3.6, §3.7)."""

# PRD §3.4 — per-square-metre cloth price keyed on the design's cloth_tier.
CLOTH_PRICE_PER_SQM_CENTS = {
    "CRUISE": 4200,
    "PERFORMANCE": 6800,
    "RACE": 9500,
    "GRAND_PRIX": 14000,
}

# PRD §3.4 — flat fee contributed by each option code on the design.
OPTION_PRICE_CENTS = {
    "BATTENS": 18000,
    "REEF_POINTS": 12000,
    "UV_STRIP": 9000,
    "NUMBERS": 4000,
    "LOGO": 6000,
}

# PRD §3.4 — class-complexity factor keyed on the boat's racing_class.
CLASS_COMPLEXITY = {
    "NONE": 1.00,
    "PHRF": 1.00,
    "ORC": 1.05,
    "J70": 1.05,
    "J105": 1.08,
    "TP52": 1.15,
}

# PRD §3.4 — heavy-duty surcharge: strictly greater than 150.00 sqm,
# base multiplied by (1 + 0.04 * reinforcement_level).
HEAVY_DUTY_AREA_THRESHOLD_SQM = 150.00
HEAVY_DUTY_SURCHARGE_PCT = 0.04

# PRD §3.7 — per-item wash prices and hull-length-tier season bases.
WASH_ITEM_PRICE_CENTS = {
    "MAIN_WASH": 14550,
    "GENOA_WASH": 12350,
    "SPINNAKER_WASH": 9875,
    "RIG_WASH": 21000,
}
SEASON_BASE_UNDER_10M_CENTS = 180000
SEASON_BASE_10M_TO_15M_CENTS = 260000
SEASON_BASE_OVER_15M_CENTS = 390000

# PRD §2.11 / §3.6 — rigging replacement clocks.
MANDATORY_REPLACEMENT_MONTHS = 120
RUNNING_REPLACEMENT_HOURS = 2000

# PRD §3.5 — warranty claim window after delivery.
WARRANTY_WINDOW_DAYS = 730

# PRD §2.10 — bay turnaround: at least one full calendar day between occupants.
BAY_TURNAROUND_GAP_DAYS = 1

# Standard measurement battery used across tests: area = 0.5*15*5 + 0.5*12*4 = 61.50 sqm.
STANDARD_MEASUREMENT = {
    "i_height_m": 12.0,
    "j_base_m": 4.0,
    "p_main_m": 15.0,
    "e_main_m": 5.0,
}
STANDARD_MEASURED_AREA_SQM = 61.50

DEFAULT_CREDIT_LIMIT_CENTS = 900_000_000
DEFAULT_BOLT_TOTAL_SQM = 500.0
DEFAULT_INSTALL_DATE = "2024-01-01T00:00:00Z"
