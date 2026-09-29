"""Domain constants declared by the PRD for the facilities capacity API."""

# ---------------------------------------------------------------- roles
ROLES = (
    "DistrictAdmin",
    "FacilitiesPlanner",
    "CapacityCertifier",
    "PermitCoordinator",
    "BuildingOfficial",
    "OperationsScheduler",
    "AssetManager",
    "CrewLead",
)

# ---------------------------------------------------------------- clock
CLOCK_AT_STARTUP = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------- pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------- chassis table
# size_class -> (length_ft, width_ft, service_draw_kw, needs_sewer, rated_seats)
CHASSIS = {
    "SINGLE_24x40": (40, 24, 12, False, 24),
    "DOUBLE_28x64": (64, 28, 20, True, 48),
    "TRIPLE_36x64": (64, 36, 28, True, 60),
}
CHASSIS_CLEARANCE_FT = 5
PAD_CLEARANCE_TOTAL_FT = 10

RATED_SEATS = {name: spec[4] for name, spec in CHASSIS.items()}

# ---------------------------------------------------------------- capacity
STATE_LOADING_SEATS = {
    "STANDARD_CLASSROOM": 25,
    "SCIENCE_LAB": 24,
    "SPED_RESOURCE": 12,
    "ART_MUSIC": 25,
    "GYM": 0,
    "LIBRARY": 0,
    "ADMIN": 0,
}
SPED_RESOURCE_FIXED_SEATS = 12
ART_MUSIC_LOAD_FACTOR = 0.50
PRIMARY_BAND = {
    "ELEMENTARY_K5": "K_3",
    "MIDDLE_68": "G7_8",
    "HIGH_912": "G9_12",
    "K8_COMBINED": "G4_6",
}
GRADE_SET = {
    "ELEMENTARY_K5": (0, 1, 2, 3, 4, 5),
    "MIDDLE_68": (6, 7, 8),
    "HIGH_912": (9, 10, 11, 12),
    "K8_COMBINED": (0, 1, 2, 3, 4, 5, 6, 7, 8),
}

# ---------------------------------------------------------------- utilization
PORTABLE_TRIGGER_PCT = 95.0
TARGET_LOADING_PCT = 95
SEATS_PER_STANDARD_PORTABLE = 24
MAX_REVISION_ROUNDS = 3

# ---------------------------------------------------------------- pad feasibility
FIRE_ACCESS_MAX_DISTANCE_FT = 150
FIRE_LANE_MIN_CLEAR_WIDTH_FT = 20
MITIGATION_ORDER = ("ELECTRICAL_UPGRADE", "SEWER_HOOKUP", "ADA_PATH_UPGRADE")

# ---------------------------------------------------------------- relocation estimate
MOBILISATION_BASE_CENTS = {
    "SINGLE_24x40": 4_500_000,
    "DOUBLE_28x64": 7_200_000,
    "TRIPLE_36x64": 9_800_000,
}
HAUL_COST_PER_MILE_CENTS = 38_000
OFF_SUMMER_MULTIPLIER = 1.35
SUMMER_WINDOW_OPEN = (6, 15)
SUMMER_WINDOW_CLOSE = (8, 15)

SITE_WORK_ELECTRICAL_CENTS = 1_850_000
SITE_WORK_SEWER_CENTS = 2_400_000
SITE_WORK_ADA_CENTS = 3_150_000

REHAB_CENTS = {"A": 0, "B": 1_250_000, "C": 4_600_000}

PERMIT_FEE_PER_DISCIPLINE_CENTS = 210_000
BASELINE_PERMIT_TYPES = ("DSA_STRUCTURAL", "FIRE_MARSHAL", "ELECTRICAL")
CONDITIONAL_PERMIT_TYPES = ("PLUMBING", "ADA_ACCESS")

CONTINGENCY_PCT = 12
CONTINGENCY_CAP_CENTS = 1_500_000
CONTINGENCY_FLOOR_CENTS = 700_000

# ---------------------------------------------------------------- alternatives
LIFECYCLE_YEARS = 20
ANNUAL_OM_CENTS = 1_150_000
REMOVAL_COST_CENTS = {
    "SINGLE_24x40": 1_600_000,
    "DOUBLE_28x64": 2_300_000,
    "TRIPLE_36x64": 2_900_000,
}
BOUNDARY_CHANGE_STUDY_CENTS = 4_200_000
BOUNDARY_TRANSPORT_PER_SEAT_PER_YEAR_CENTS = 96_000
BOUNDARY_TRANSPORT_YEARS = 5
PERMANENT_ADDITION_PER_SEAT_CENTS = 3_850_000

SOFT_COST_TIER_BREAK_LOW_CENTS = 50_000_000
SOFT_COST_TIER_BREAK_HIGH_CENTS = 150_000_000
SOFT_COST_PCT_LOW = 9
SOFT_COST_PCT_MID = 13
SOFT_COST_PCT_HIGH = 17

OPTION_TIE_ORDER = ("RELOCATE", "BOUNDARY_CHANGE", "PERMANENT_ADDITION")
RELIANCE_YEARS_BLOCKING_RELOCATE = 5
COST_BASIS_LIFECYCLE = "LIFECYCLE_20YR"
COST_BASIS_IMMEDIATE = "IMMEDIATE_CAPITAL"

# ---------------------------------------------------------------- scheduling
PAD_TURNAROUND_DAYS = 7
PERMIT_VALIDITY_DAYS = 180
MAX_LIFETIME_RELOCATIONS = 4

# ---------------------------------------------------------------- salvage
SALVAGE_USEFUL_LIFE_YEARS = 20
SALVAGE_FLOOR_PCT = 5
CONDITION_MULTIPLIER = {"A": 1.00, "B": 0.80, "C": 0.55, "D": 0.25}
SALE_MIN_RECOVERY_PCT = 70
CONDITION_GRADE_RANK = ("A", "B", "C")

# ---------------------------------------------------------------- reliance
LONG_TERM_RELIANCE_SHARE_PCT = 15.0
MONITOR_SHARE_PCT = 5.0
