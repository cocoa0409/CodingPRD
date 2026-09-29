"""Domain thresholds and literal figures the PRD pins for this API."""

# --------------------------------------------------------------------- clock
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
ARENA_LOCAL_UTC_OFFSET_HOURS = -4

# ------------------------------------------------------------ hold windows
HOLD_WINDOW_HOURS = {
    "TIER_1": 14 * 24,
    "TIER_2": 7 * 24,
    "TIER_3": 3 * 24,
    "OPEN": 24,
}

TIER_ORDINALS = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3, "OPEN": 4}
MIN_UPHELD_PRIORITY_DELTA = 1
GRANTED_CHALLENGE_CREDITS = 2

# ----------------------------------------------------- displacement waterfall
DISPLACEMENT_BASE_CENTS = {"TIER_2": 650_000, "TIER_3": 250_000, "OPEN": 120_000}
DISPLACEMENT_NOTICE_DAYS_HIGH = 90
DISPLACEMENT_NOTICE_DAYS_MID = 30
DISPLACEMENT_NOTICE_FACTOR_HIGH = 0.25
DISPLACEMENT_NOTICE_FACTOR_MID = 0.60
DISPLACEMENT_NOTICE_FACTOR_FULL = 1.00
ADMIN_RATE_HIGH_SUBTOTAL_CENTS = 400_000
ADMIN_RATE_MID_SUBTOTAL_CENTS = 150_000
ADMIN_RATE_HIGH = 0.08
ADMIN_RATE_MID = 0.05
ADMIN_RATE_LOW = 0.03

# ------------------------------------------------------- turnaround planning
ICE_ADDER_COVER_MINUTES = 90
ICE_ADDER_MELT_MINUTES = 600
ICE_ADDER_UNCOVER_MINUTES = 75
ICE_ADDER_BUILD_MINUTES = 720
SEATING_ADDER_MINUTES = {
    "FULL_BOWL": 0,
    "RETRACTABLE_IN": 120,
    "CURTAINED_HALF": 180,
}
PANELS_PER_SET = 40
MINUTES_PER_PANEL_SET = 15
CREW_FACTOR_MIN = 0.5
CREW_FACTOR_MAX = 2.0
OVERNIGHT_SLOWDOWN_MULTIPLIER = 1.15
OVERNIGHT_LOWER_LOCAL_HOUR = 6
CHANGEOVER_DEBT_FREEZE_MINUTES = 180

# ----------------------------------------------------------------- ice deck
MIN_DEHUM_FRACTION = 0.25
CONDENSATION_BLOCK_THRESHOLD = 40.00
CONDENSATION_WEIGHT_DEHUM = 0.45
CONDENSATION_WEIGHT_COVER = 0.30
CONDENSATION_WEIGHT_THICKNESS = 0.25
COVER_LOAD_HOURS = 72
NOMINAL_SHEET_THICKNESS_MM = 32
DEFAULT_SHEET_THICKNESS_MM = 32
SHEET_THICKNESS_MIN_MM = 18
SHEET_THICKNESS_MAX_MM = 45
COVER_CYCLE_LIMIT = 3
ICE_BUILD_MINUTES = 12 * 60

# ---------------------------------------------------------------- labor cost
CRAFT_HOURLY_RATE_CENTS = {
    "STAGEHAND": 4_800,
    "RIGGER": 7_200,
    "ICE_TECH": 5_600,
    "ELECTRICIAN": 6_900,
    "CONVERSION_CREW": 4_200,
}
OT_THRESHOLD_HOURS = 8
OT_WEIGHT = 1.5
OVERNIGHT_LABOR_MULTIPLIER = 1.35
DEFAULT_GUARANTEED_HOURS = 4
CANCELLATION_FREE_NOTICE_HOURS = 48
CANCELLATION_QUARTER_NOTICE_HOURS = 12
CANCELLATION_QUARTER_FRACTION = 0.25
CANCELLATION_HALF_FRACTION = 0.50

# ------------------------------------------------------------------ defaults
DEFAULT_MIN_TURNAROUND_BUFFER_MINUTES = 45
DEFAULT_DOCK_BUFFER_MINUTES = 30
DEFAULT_OVERNIGHT_SHIFT_START_LOCAL_HOUR = 22
DEFAULT_SERVICE_INTERVAL_CYCLES = 12

# ----------------------------------------------------------------- pagination
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --------------------------------------------- readiness projection ordering
BLOCKING_REASON_ORDER = [
    "INCOMING_BOOKING_NOT_CONFIRMED",
    "FLOOR_PROTECTION_SHORTFALL",
    "FLOOR_INCOMPLETE",
    "SEATING_INCOMPLETE",
    "INFRA_INCOMPLETE",
    "CHANGEOVER_DEBT_FREEZE",
]

# --------------------------------------------------- shared fixture literals
DIRECTOR_USER_ID = "dir-lakeside"
SUPERVISOR_USER_ID = "sup-alpha"
SECOND_SUPERVISOR_USER_ID = "sup-beta"
BOOKING_MANAGER_USER_ID = "mgr-lakeside"
LABOR_COORDINATOR_USER_ID = "lab-lakeside"

VENUE_DEFAULTS = {
    "name": "Lakeside Arena",
    "rigging_capacity_kg": 20_000,
    "dock_count": 4,
    "max_bowl_seats": 18_000,
    "crew_headcount_cap": 60,
    "min_turnaround_buffer_minutes": 45,
    "dock_buffer_minutes": 30,
    "overnight_shift_start_local_hour": 22,
}

PROFILE_ICE = {
    "code": "ICE_HOCKEY",
    "requires_ice": True,
    "ice_cover_required": False,
    "seating_mode": "FULL_BOWL",
    "nominal_seats": 17_000,
    "base_changeover_minutes": 240,
    "crew_size_required": 30,
    "floor_protection_panels_required": 0,
    "dehumidification_required_lph": 120,
    "rigging_points_required": 40,
}

PROFILE_CONCERT = {
    "code": "CONCERT_END_STAGE",
    "requires_ice": False,
    "ice_cover_required": True,
    "seating_mode": "CURTAINED_HALF",
    "nominal_seats": 9_000,
    "base_changeover_minutes": 300,
    "crew_size_required": 40,
    "floor_protection_panels_required": 120,
    "dehumidification_required_lph": 0,
    "rigging_points_required": 220,
}

PROFILE_COURT = {
    "code": "COURT_BASKETBALL",
    "requires_ice": False,
    "ice_cover_required": True,
    "seating_mode": "RETRACTABLE_IN",
    "nominal_seats": 15_000,
    "base_changeover_minutes": 180,
    "crew_size_required": 24,
    "floor_protection_panels_required": 80,
    "dehumidification_required_lph": 0,
    "rigging_points_required": 60,
}

PROFILE_FAMILY = {
    "code": "FAMILY_SHOW",
    "requires_ice": False,
    "ice_cover_required": True,
    "seating_mode": "FULL_BOWL",
    "nominal_seats": 12_000,
    "base_changeover_minutes": 200,
    "crew_size_required": 25,
    "floor_protection_panels_required": 40,
    "dehumidification_required_lph": 0,
    "rigging_points_required": 90,
}
