"""Domain thresholds and money constants from the PRD's calculation rules (§2.9, §3)."""

THRESHOLDS = {
    # PRD §3.6: go/no-go and start-ignition weather freshness
    "OBSERVATION_FRESHNESS_MINUTES": 60,
    # PRD §3.6: neighbor notification lead time before briefing
    "NOTIFICATION_LEAD_TIME_HOURS": 48,
    # PRD §3.6: parcel monitoring gap after a closed execution
    "PARCEL_MONITORING_GAP_DAYS": 30,
    # PRD §3.1: landowner standing suspension delay after adjudication
    "LANDOWNER_SUSPENSION_DAYS": 30,
    # PRD §3.1: contractor standing suspension threshold
    "CONTRACTOR_NO_SHOW_SUSPEND": 2,
    # PRD §2.10: fund posture threshold
    "FUND_LOW_THRESHOLD_CENTS": 200_000,
    # PRD §3.8: agreement lifetime after approval
    "AGREEMENT_LIFETIME_DAYS": 365,
    # PRD §3.8: effectiveness factor bands (inclusive at 80 and 50)
    "EFFECTIVENESS_FULL_THRESHOLD": 80,
    "EFFECTIVENESS_PARTIAL_THRESHOLD": 50,
}

# PRD §3.1: hazard score weights
FUEL_WEIGHT = {"GRASS": 20, "BRUSH": 35, "TIMBER": 50}
SLOPE_WEIGHT = {"FLAT": 0, "MODERATE": 10, "STEEP": 20}
WUI_BONUS = 20

# PRD §3.2: certification gates (both bounds inclusive)
CERT_GATES = {
    "RXB1": {"max_acres": 40, "max_hazard": 40},
    "RXB2": {"max_acres": 200, "max_hazard": 70},
    # RXB3 unrestricted
}

# PRD §3.5: required holding force constants
FUEL_FACTOR = {"GRASS": 1.0, "BRUSH": 1.5, "TIMBER": 2.0}
ACRES_PER_ENGINE = 40
ACRES_PER_HAND_CREW = 80
ACRES_PER_WATER_TENDER = 60
WUI_ENGINE_BONUS = 2
STEEP_CREW_MULTIPLIER = 2
DOZER_TIMBER_ACRE_THRESHOLD = 100

# PRD §3.8: cost-share rates and tier shares
RATE_CENTS = {"GRASS": 15_327, "BRUSH": 28_750, "TIMBER": 46_000}
SHARE_PCT = {"STANDARD": 0.50, "PRIORITY": 0.75, "LEGACY": 0.65}
PROVISIONAL_INSTALLMENT_FRACTION = 0.5
EFFECTIVENESS_PARTIAL_FACTOR = 0.75

# PRD §3.8: monitoring effectiveness category weights
CATEGORY_WEIGHT = {"BROADCAST": 1.0, "UNDERSTORY": 0.8, "PILE_BURN": 0.6}

# PRD §3.9: suppression cost allocation
PER_ACRE_CENTS = 25_000
NEGLIGENCE_MULTIPLIER = 1.5

# PRD §3.9: fund payout cap fraction of the pre-debit balance
FUND_PAYOUT_FRACTION = 0.5

# Standard temporal landmarks used across the scenario chains
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
BURN_DAY = "2026-05-12"
BURN_DAY_TS = "2026-05-12T07:30:00Z"
PLAN_WINDOW_START = "2026-05-10"
PLAN_WINDOW_END = "2026-05-20"

# Standard prescription used by most fixtures (six numbers, min <= max)
PRESCRIPTION_DEFAULTS = {
    "max_wind_mph": 15,
    "min_fuel_moisture_pct": 8,
    "max_fuel_moisture_pct": 20,
    "min_rh_pct": 25,
    "min_temp_f": 40,
    "max_temp_f": 85,
    "min_mixing_height_ft": 1500,
}

# A comfortably in-prescription weather reading for the burn-day chains
WEATHER_IN_PRESCRIPTION = {
    "wind_mph": 10,
    "fuel_moisture_pct": 12,
    "rh_pct": 40,
    "temp_f": 60,
    "mixing_height_ft": 2000,
}

# The six required go/no-go checklist items (PRD §3.6)
CHECKLIST_ITEMS = [
    "permit_verified",
    "crew_briefed",
    "communications_check",
    "escape_routes_reviewed",
    "weather_within_prescription",
    "holding_resources_ready",
]
