"""Closed vocabularies and calculation constants (PRD 2.11 / 3.x, SCAFFOLD 1.3)."""

from decimal import Decimal

# --------------------------------------------------------------- roles -----
ROLES = [
    "DistrictAdmin",
    "FacilitiesPlanner",
    "CapacityCertifier",
    "PermitCoordinator",
    "BuildingOfficial",
    "OperationsScheduler",
    "AssetManager",
    "CrewLead",
]
ALL_EXCEPT_CREW_LEAD = [r for r in ROLES if r != "CrewLead"]
ANY_ROLE = list(ROLES)

# ---------------------------------------------------------- enumerations ---
GRADE_CONFIGURATIONS = ["ELEMENTARY_K5", "MIDDLE_68", "HIGH_912", "K8_COMBINED"]
GRADE_BANDS = ["K_3", "G4_6", "G7_8", "G9_12"]
ROOM_TYPES = [
    "STANDARD_CLASSROOM", "SCIENCE_LAB", "SPED_RESOURCE", "ART_MUSIC",
    "GYM", "LIBRARY", "ADMIN",
]
ROOM_STATUSES = ["IN_SERVICE", "OUT_OF_SERVICE_RENOVATION", "DECOMMISSIONED"]
PROGRAM_TYPES = [
    "SPED_SELF_CONTAINED", "DUAL_LANGUAGE", "TITLE_I_INTERVENTION", "CTE_LAB",
]
PROJECTION_SOURCES = ["COHORT_SURVIVAL", "DEVELOPER_YIELD"]
CONFIDENCE_TIERS = ["HIGH", "MEDIUM", "LOW"]
STUDY_METHODS = ["STATE_LOADING_STANDARD", "DISTRICT_POLICY"]
STUDY_STATUSES = ["DRAFT", "SUBMITTED", "RETURNED", "CERTIFIED", "SUPERSEDED"]
SIZE_CLASSES = ["SINGLE_24x40", "DOUBLE_28x64", "TRIPLE_36x64"]
CONDITION_GRADES = ["A", "B", "C", "D"]
CONDITION_STATUSES = ["SERVICEABLE", "NEEDS_REHAB", "UNSAFE"]
ALLOCATION_STATUSES = [
    "IN_STORAGE", "RESERVED", "SCHEDULED", "INSTALLED", "PENDING_REMOVAL",
    "DISPOSED",
]
FEASIBILITY_STATUSES = [
    "UNASSESSED", "FEASIBLE", "FEASIBLE_WITH_MITIGATION", "INFEASIBLE",
]
REQUEST_STATUSES = [
    "DRAFT", "SITE_ASSESSED", "PERMIT_PENDING", "PERMITTED", "SCHEDULED",
    "INSTALLED", "DECOMMISSION_REQUESTED", "DECOMMISSIONED", "REJECTED",
    "WITHDRAWN",
]
COST_RECOMMENDATIONS = ["RELOCATE", "BOUNDARY_CHANGE", "PERMANENT_ADDITION"]
PERMIT_TYPES = [
    "DSA_STRUCTURAL", "FIRE_MARSHAL", "ELECTRICAL", "PLUMBING", "ADA_ACCESS",
]
PERMIT_STATUSES = ["SUBMITTED", "CORRECTIONS_REQUIRED", "APPROVED", "DENIED"]
PERMIT_DECISIONS = ["APPROVED", "CORRECTIONS_REQUIRED", "DENIED"]
WORK_TYPES = ["SET", "RELOCATE"]
SCHEDULE_STATUSES = ["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
DISPOSAL_METHODS = ["SALE", "SCRAP", "TRANSFER_TO_COUNTY"]
VALUATION_BASES = ["STRAIGHT_LINE", "CONDITION_ADJUSTED"]
RELIANCE_FLAGS = ["NONE", "MONITOR", "LONG_TERM_RELIANCE"]
COST_BASES = ["LIFECYCLE_20YR", "IMMEDIATE_CAPITAL"]

# ------------------------------------------------- program capacity seats --
PRIMARY_BAND = {
    "ELEMENTARY_K5": "K_3",
    "MIDDLE_68": "G7_8",
    "HIGH_912": "G9_12",
    "K8_COMBINED": "G4_6",
}
GRADE_SET = {
    "ELEMENTARY_K5": [0, 1, 2, 3, 4, 5],
    "MIDDLE_68": [6, 7, 8],
    "HIGH_912": [9, 10, 11, 12],
    "K8_COMBINED": [0, 1, 2, 3, 4, 5, 6, 7, 8],
}
SPED_FIXED_SEATS = 12
ART_MUSIC_LOADING_FACTOR = Decimal("0.50")
STATE_LOADING = {
    "STANDARD_CLASSROOM": 25,
    "SCIENCE_LAB": 24,
    "SPED_RESOURCE": 12,
    "ART_MUSIC": 25,
    "GYM": 0,
    "LIBRARY": 0,
    "ADMIN": 0,
}

# ----------------------------------------- utilization / portable trigger --
PORTABLE_TRIGGER_PCT = Decimal("95.0")
TARGET_UTILIZATION_PCT = 95
STANDARD_PORTABLE_SEATS = 24

# --------------------------------------------------------- chassis & pads --
UNIT_DIMS = {
    "SINGLE_24x40": {"length_ft": 40, "width_ft": 24, "service_kw": 12,
                     "needs_sewer": False, "rated_seats": 24},
    "DOUBLE_28x64": {"length_ft": 64, "width_ft": 28, "service_kw": 20,
                     "needs_sewer": True, "rated_seats": 48},
    "TRIPLE_36x64": {"length_ft": 64, "width_ft": 36, "service_kw": 28,
                     "needs_sewer": True, "rated_seats": 60},
}
RATED_SEATS = {k: v["rated_seats"] for k, v in UNIT_DIMS.items()}
PAD_CLEARANCE_FT = 5
FIRE_ACCESS_MAX_DISTANCE_FT = 150
FIRE_LANE_MIN_CLEAR_WIDTH_FT = 20
DEFAULT_SIZE_CLASS = "SINGLE_24x40"

# ------------------------------------------------ relocation cost estimate -
MOVE_BASE_CENTS = {
    "SINGLE_24x40": 4500000,
    "DOUBLE_28x64": 7200000,
    "TRIPLE_36x64": 9800000,
}
HAUL_RATE_CENTS_PER_MILE = 38000
ELECTRICAL_UPGRADE_CENTS = 1850000
SEWER_HOOKUP_CENTS = 2400000
ADA_RETROFIT_CENTS = 3150000
REHAB_CENTS_BY_GRADE = {"A": 0, "B": 1250000, "C": 4600000, "D": 0}
OFF_SUMMER_MULTIPLIER = Decimal("1.35")
CONTINGENCY_PCT = Decimal("0.12")
CONTINGENCY_FLOOR_CENTS = 700000
CONTINGENCY_CAP_CENTS = 1500000
PERMIT_FEE_CENTS_PER_TYPE = 210000
SUMMER_WINDOW_START = (6, 15)
SUMMER_WINDOW_END = (8, 15)

# ------------------------------------------- alternative cost comparison ---
ANNUAL_PORTABLE_OM_CENTS = 1150000
RELIANCE_HORIZON_YEARS = 20
REMOVAL_CENTS_BY_SIZE = {
    "SINGLE_24x40": 1600000,
    "DOUBLE_28x64": 2300000,
    "TRIPLE_36x64": 2900000,
}
BOUNDARY_STUDY_FIXED_CENTS = 4200000
BOUNDARY_TRANSPORT_CENTS_PER_SEAT_PER_YEAR = 96000
BOUNDARY_HORIZON_YEARS = 5
ADDITION_CENTS_PER_SEAT = 3850000
SOFT_COST_TIER_BREAKS_CENTS = [50000000, 150000000]
SOFT_COST_PCTS = [Decimal("0.09"), Decimal("0.13"), Decimal("0.17")]
LONG_TERM_RELIANCE_YEARS = 5

# ------------------------------------------------------- salvage / decay ---
USEFUL_LIFE_YEARS = 20
SALVAGE_FLOOR_PCT = Decimal("0.05")
CONDITION_MULTIPLIER = {
    "A": Decimal("1.00"),
    "B": Decimal("0.80"),
    "C": Decimal("0.55"),
    "D": Decimal("0.25"),
}
MIN_SALE_RECOVERY_PCT = Decimal("0.70")

# ------------------------------------------------------------- reliance ----
MONITOR_SHARE_PCT = Decimal("5.0")
LONG_TERM_SHARE_PCT = Decimal("15.0")
RELIANCE_ROUNDING_BASIS = "PER_SCHOOL_THEN_AVERAGE"

# ---------------------------------------------------- unit selection ------
MAX_LIFETIME_RELOCATIONS = 4
MIN_SEATS_PER_UNIT = 24
CONDITION_GRADE_RANK = {"A": 1, "B": 2, "C": 3, "D": 4}

# ------------------------------------------------------------- misc -------
PERMIT_VALIDITY_DAYS = 180
PAD_TURNAROUND_BUFFER_DAYS = 7
MAX_REVISION_ROUNDS = 3
BASELINE_PERMIT_TYPES = ["DSA_STRUCTURAL", "FIRE_MARSHAL", "ELECTRICAL"]
NON_TERMINAL_REQUEST_STATUSES_FOR_WITHDRAW = [
    "DRAFT", "SITE_ASSESSED", "PERMIT_PENDING", "PERMITTED", "SCHEDULED",
]
