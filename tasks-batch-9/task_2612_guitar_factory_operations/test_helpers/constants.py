"""
Domain constants, enum vocabularies and the reference payloads the composite
builders lean on.

Nothing here is a computed expectation: every figure a test asserts is written
out literally in that test, so a mistake in a shared helper can never quietly
become the expected answer.
"""

# ---------------------------------------------------------------------------
# The logical shop clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
ROOM_TYPES = ["DRY_STORE", "KILN", "BUILD_ROOM", "FINISH_BOOTH"]
CLIMATE_STATUSES = ["IN_SPEC", "OUT_OF_SPEC", "QUARANTINED"]
SPECIES = [
    "SITKA_SPRUCE",
    "HONDURAN_MAHOGANY",
    "HARD_MAPLE",
    "EAST_INDIAN_ROSEWOOD",
    "BRAZILIAN_ROSEWOOD",
    "EBONY",
]
CITES_APPENDICES = ["NONE", "APPENDIX_II", "APPENDIX_I"]
PERMIT_STATUSES = ["NOT_REQUIRED", "PENDING", "VERIFIED", "INVALID"]
LOT_STATUSES = [
    "RECEIVED",
    "PERMIT_HOLD",
    "KILN_DRYING",
    "CONDITIONED",
    "RELEASED",
    "DEPLETED",
    "REJECTED",
]
GRADES = ["AAA", "AA", "A", "UTILITY"]
BILLET_STATUSES = ["AVAILABLE", "RESERVED", "CONSUMED", "SCRAPPED", "QUARANTINED"]
COMPONENT_TYPES = ["BODY_TOP", "BODY_BACK", "NECK", "FINGERBOARD", "BRACE", "BINDING"]
COMPONENT_STATUSES = [
    "ROUGH_SAWN",
    "CNC_ROUTED",
    "HAND_SHAPED",
    "QC_HELD",
    "REWORK",
    "ACCEPTED",
    "INSTALLED",
    "SCRAPPED",
]
QC_HOLD_REASONS = [
    "NONE",
    "DIMENSION",
    "GRAIN_RUNOUT",
    "PROTECTED_SPECIES",
    "CLIMATE_EXCURSION",
]
STATION_TYPES = [
    "CNC_ROUTER",
    "HAND_SHAPING",
    "BRACING",
    "BINDING",
    "ASSEMBLY",
    "FRETWORK",
    "SETUP_BENCH",
]
RESERVATION_STATUSES = ["HELD", "CONSUMED", "RELEASED"]
OPTION_GROUPS = ["TOP_WOOD", "INLAY", "HARDWARE", "ELECTRONICS", "NECK_PROFILE"]
COMPLEXITY_CLASSES = ["STANDARD", "ARTISAN", "MASTER"]
FINISH_SYSTEMS = ["NITRO", "POLY"]
ARTIST_TIERS = ["NONE", "ENDORSER", "SIGNATURE"]
BUILD_STAGES = [
    "DRAFT",
    "COMPONENTS_RELEASED",
    "IN_ASSEMBLY",
    "IN_FINISH",
    "FINISH_HELD",
    "FINISH_CURED",
    "FRETWORK",
    "SETUP",
    "INSPECTION",
    "COMPLIANCE_HOLD",
    "SERIALIZED",
    "SCRAPPED",
]
COMMERCIAL_STATUSES = [
    "QUOTED",
    "CONFIRMED",
    "OPTIONS_LOCKED",
    "AT_RISK",
    "INVOICED",
    "CLOSED",
    "CANCELLED",
]
SELECTION_STATUSES = ["PENDING_APPROVAL", "SELECTED", "REJECTED", "LOCKED"]
FINISH_RUN_STATUSES = [
    "SPRAYING",
    "CURING",
    "CURE_SUSPENDED",
    "BUFFING",
    "COMPLETED",
    "REJECTED",
]
INSPECTION_STATUSES = ["OPEN", "MEASURED", "SIGNED", "FAILED"]
VERDICTS = ["PENDING", "PASS", "FAIL"]
SHOP_STATUSES = ["APPLIED", "AUTHORIZED", "SUSPENDED"]
AUTHORIZATION_LEVELS = ["NONE", "WARRANTY_ONLY", "FULL_SERVICE", "CUSTOM_SHOP_CERTIFIED"]
WARRANTY_STATUSES = ["ACTIVE", "VOID"]
SHIPMENT_STATUSES = [
    "DOCS_PENDING",
    "DOCS_ATTACHED",
    "DOCS_REJECTED",
    "RELEASED",
    "EXPORTED",
]

# ---------------------------------------------------------------------------
# Declared defaults, so a test can name the value it expects the server to fill
# ---------------------------------------------------------------------------
DEFAULT_RH_TOLERANCE_PCT = 3.0
DEFAULT_CHANGEOVER_MINUTES = 30
DEFAULT_THICKNESS_TOLERANCE_MM = 0.15
DEFAULT_REQUIRED_ROOM_TYPE = "BUILD_ROOM"
DEFAULT_REQUIRES_FINISH_SYSTEM = "ANY"
DEFAULT_QUANTITY = 1

# ---------------------------------------------------------------------------
# Reference rooms
# ---------------------------------------------------------------------------
DRY_STORE_1 = {
    "room_code": "DRY-1",
    "room_type": "DRY_STORE",
    "target_rh_pct": 45.0,
    "rh_tolerance_pct": 3.0,
    "target_temp_c": 21.0,
    "capacity_slots": 20,
}
BUILD_ROOM_1 = {
    "room_code": "BR-1",
    "room_type": "BUILD_ROOM",
    "target_rh_pct": 45.0,
    "rh_tolerance_pct": 3.0,
    "target_temp_c": 21.0,
    "capacity_slots": 10,
}
FINISH_BOOTH_1 = {
    "room_code": "FB-1",
    "room_type": "FINISH_BOOTH",
    "target_rh_pct": 50.0,
    "rh_tolerance_pct": 5.0,
    "target_temp_c": 21.0,
    "capacity_slots": 1,
}
FINISH_BOOTH_ROOMY = {
    "room_code": "FB-1",
    "room_type": "FINISH_BOOTH",
    "target_rh_pct": 50.0,
    "rh_tolerance_pct": 3.0,
    "target_temp_c": 21.0,
    "capacity_slots": 4,
}

# ---------------------------------------------------------------------------
# Reference stations
# ---------------------------------------------------------------------------
CNC_STATION = {
    "station_code": "CNC-1",
    "station_type": "CNC_ROUTER",
    "changeover_minutes": 30,
}
HAND_SHAPING_STATION = {
    "station_code": "HS-1",
    "station_type": "HAND_SHAPING",
    "changeover_minutes": 30,
}

# ---------------------------------------------------------------------------
# Reference engineering specification
# ---------------------------------------------------------------------------
SPEC_TOP_OM = {
    "spec_code": "TOP-OM",
    "component_type": "BODY_TOP",
    "required_species_codes": ["SITKA_SPRUCE", "EAST_INDIAN_ROSEWOOD"],
    "min_grade": "AA",
    "nominal_board_feet": 6.00,
    "target_thickness_mm": 2.90,
    "thickness_tolerance_mm": 0.10,
    "cnc_minutes": 45,
    "hand_shape_minutes": 60,
    "required_room_type": "BUILD_ROOM",
}

# ---------------------------------------------------------------------------
# Reference catalog rows
# ---------------------------------------------------------------------------
OPTION_VINE_INLAY = {
    "option_code": "INL-VINE",
    "option_group": "INLAY",
    "upcharge_cents": 130000,
    "complexity_class": "ARTISAN",
    "lead_time_days": 45,
    "incompatible_option_codes": ["INL-DOT"],
}
OPTION_DOT_INLAY = {
    "option_code": "INL-DOT",
    "option_group": "INLAY",
    "upcharge_cents": 12004,
    "complexity_class": "ARTISAN",
    "lead_time_days": 10,
}
OPTION_GOLD_HARDWARE = {
    "option_code": "HW-GOLD",
    "option_group": "HARDWARE",
    "upcharge_cents": 22004,
    "complexity_class": "ARTISAN",
    "lead_time_days": 14,
}
OPTION_PREMIUM_ELECTRONICS = {
    "option_code": "EL-PREMIUM",
    "option_group": "ELECTRONICS",
    "upcharge_cents": 32004,
    "complexity_class": "ARTISAN",
    "lead_time_days": 5,
}
OPTION_MASTER_TOP = {
    "option_code": "TW-MASTER",
    "option_group": "TOP_WOOD",
    "upcharge_cents": 95000,
    "complexity_class": "MASTER",
    "lead_time_days": 30,
}
OPTION_NITRO_ONLY = {
    "option_code": "NP-NITRO",
    "option_group": "NECK_PROFILE",
    "upcharge_cents": 12004,
    "complexity_class": "ARTISAN",
    "lead_time_days": 5,
    "requires_finish_system": "NITRO",
}

# ---------------------------------------------------------------------------
# Fiscal and physical constants the specification pins by name
# ---------------------------------------------------------------------------
MIN_DEPOSIT_BP = 1000
CANCEL_FORFEIT_BP = 2500
MIN_SETTLE_BP = 2000
CUSTOM_SHOP_SURCHARGE_BP = 1200
COMPLEXITY_MULTIPLIER_BP = {"STANDARD": 10000, "ARTISAN": 13500, "MASTER": 17500}
ARTIST_DISCOUNT_BP = {"NONE": 0, "ENDORSER": 1000, "SIGNATURE": 2500}
KERF_BP = 300
LOT_SAWING_ALLOWANCE_BP = 30
SHRINKAGE_BP_PER_PCT = 45
MOISTURE_TARGET_PCT = 8.0
MOISTURE_BAND_MIN_PCT = 6.0
MOISTURE_BAND_MAX_PCT = 8.0
BASE_COAT_COUNT = {"NITRO": 8, "POLY": 3}
BASE_CURE_HOURS = {"NITRO": 336, "POLY": 72}
EXTRA_COAT_HOURS = {"NITRO": 18, "POLY": 6}
MIN_CURE_HOURS = {"NITRO": 240, "POLY": 48}
SPRAY_HOURS = 4
PASS_SCORE_MAX = 10.00
MAX_REWORK_ROUNDS = 3
MAX_COMPONENT_REWORKS = 2
BASE_LEAD_DAYS = 60
STANDARD_COVERAGE_MONTHS = 24
CUSTOM_SHOP_COVERAGE_MONTHS = 60
DOC_FEE_FLOOR_CENTS = 3000
CITES_ENDORSEMENT_CENTS = 12500
INSURANCE_BP = 90
