"""Domain constants and thresholds for the County Address and Emergency Response GIS API."""

# --- Logical clock -----------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00.000Z"
CLOCK_STARTUP_INPUT = "2026-08-01T00:00:00Z"

# --- Roles -------------------------------------------------------------------
ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_GIS_ANALYST = "GisAnalyst"
ROLE_QC_CERTIFIER = "QcCertifier"
ROLE_PROVISIONING_OFFICER = "ProvisioningOfficer"
ROLE_PERMIT_COORDINATOR = "PermitCoordinator"
ROLE_AGENCY_LIAISON = "AgencyLiaison"

ALL_ROLES = [
    ROLE_SYSTEM_ADMIN,
    ROLE_GIS_ANALYST,
    ROLE_QC_CERTIFIER,
    ROLE_PROVISIONING_OFFICER,
    ROLE_PERMIT_COORDINATOR,
    ROLE_AGENCY_LIAISON,
]

# --- Service types: ORDERED constant (LAW, FIRE, EMS) ------------------------
SERVICE_TYPES = ["LAW", "FIRE", "EMS"]

# --- Pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Field length bounds -----------------------------------------------------
JURISDICTION_NAME_MIN = 1
JURISDICTION_NAME_MAX = 120
JURISDICTION_CODE_MIN = 2
JURISDICTION_CODE_MAX = 8
POSTAL_CITY_MIN = 1
POSTAL_CITY_MAX = 60
AGENCY_NAME_MAX = 120
CELL_CODE_MAX = 12
ROAD_NAME_MAX = 120
PERMIT_NUMBER_MAX = 32
PARCEL_ID_MAX = 32
UNIT_ID_MAX = 8
HOUSE_NUMBER_SUFFIX_MAX = 4
PROPOSED_VALUE_MAX = 120
CASE_DESCRIPTION_MAX = 500

HOUSE_NUMBER_MIN = 0
HOUSE_NUMBER_MAX = 999999
REQUESTED_UNIT_COUNT_MIN = 0
REQUESTED_UNIT_COUNT_MAX = 99

# --- Road name normalization abbreviations (last token only) -----------------
ROAD_TYPE_EXPANSIONS = {
    "ST": "STREET",
    "RD": "ROAD",
    "AVE": "AVENUE",
    "DR": "DRIVE",
    "LN": "LANE",
    "HWY": "HIGHWAY",
    "CT": "COURT",
    "BLVD": "BOULEVARD",
}

# --- Confidence scoring ------------------------------------------------------
SOURCE_BASE_WEIGHT = {
    "PARCEL": 70,
    "PERMIT": 60,
    "POSTAL": 45,
    "FIELD": 80,
}
GEOMETRY_VERIFIED_BONUS = 12
POSTAL_CITY_MATCH_BONUS = 8
BASE_ADDRESS_BONUS = 6
ROAD_STATUS_PENALTY = {
    "DRAFT": 15,
    "VALIDATED": 5,
    "PUBLISHED": 0,
}
CERTIFIED_FULL_COVERAGE_BONUS = 10
CERTIFIED_OPEN_CASE_PENALTY = 20
CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 100

# --- QC scoring --------------------------------------------------------------
SEVERITY_WEIGHT = {
    "BLOCKING": 12.5,
    "WARNING": 4.0,
    "INFO": 1.5,
}
CATEGORY_WEIGHT = {
    "ADDRESS": 0.45,
    "ROAD": 0.30,
    "BOUNDARY": 0.25,
}
QUALITY_TIER_THRESHOLDS = [("A", 95), ("B", 85), ("C", 70)]
TIER_WAIVER_RATE = {
    "A": 1.0,
    "B": 2.5,
    "C": 5.0,
    "D": 8.0,
}
PROVISIONING_ELIGIBILITY_MINIMUM = 90.00
LOW_CONFIDENCE_THRESHOLD = 70

# --- Defect catalogue: code -> (severity, category, jurisdiction_scope_only) --
DEFECT_CATALOGUE = {
    "ADDRESS_MISSING_GEOMETRY": ("BLOCKING", "ADDRESS", False),
    "ADDRESS_UNCOVERED_CELL": ("BLOCKING", "ADDRESS", True),
    "ADDRESS_POSTAL_CITY_MISMATCH": ("WARNING", "ADDRESS", False),
    "ADDRESS_UNIT_TYPE_MISSING": ("WARNING", "ADDRESS", False),
    "ADDRESS_LOW_CONFIDENCE": ("INFO", "ADDRESS", False),
    "ROAD_UNVALIDATED": ("BLOCKING", "ROAD", False),
    "ROAD_RANGE_OVERLAP": ("BLOCKING", "ROAD", False),
    "ROAD_NAME_NOT_NORMALIZED": ("WARNING", "ROAD", False),
    "ROAD_QC_DIRTY": ("WARNING", "ROAD", False),
    "ROAD_NO_ADDRESSES": ("INFO", "ROAD", False),
    "BOUNDARY_COVERAGE_GAP": ("BLOCKING", "BOUNDARY", True),
    "PROPOSED_COVERAGE_OVERLAP": ("WARNING", "BOUNDARY", True),
    "BOUNDARY_STALE_WINDOW": ("INFO", "BOUNDARY", True),
}

# --- Provisioning cadence intervals, in days ---------------------------------
CADENCE_INTERVAL_DAYS = {
    "DISPATCH_E911": 7,
    "MAPPING": 14,
    "PUBLIC": 30,
}

# --- Coverage horizon --------------------------------------------------------
FORWARD_HORIZON_DAYS = 30

# --- Negotiation -------------------------------------------------------------
ROUND_LIMIT = 3
ESCALATION_ROUND_NUMBER = 4

# --- Retirement reason vocabulary -------------------------------------------
ADDRESS_RETIRE_REASONS = [
    "ROAD_RETIRED",
    "PARENT_RETIRED",
    "REPLACED",
    "ANALYST_RETIRED",
    "REQUEST_VOIDED",
]
