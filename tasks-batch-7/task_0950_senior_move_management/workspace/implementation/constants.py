"""Every named constant declared by the specification.

Nothing here is business logic; the formulas that consume these live in calc.py.
"""

# ---- roles -----------------------------------------------------------------
ROLES = [
    "PLATFORM_ADMIN",
    "MOVE_MANAGER",
    "BILLING_ADMIN",
    "CREW_LEAD",
    "VENDOR",
    "CLIENT",
    "FAMILY_MEMBER",
    "POWER_OF_ATTORNEY",
]

# Roles whose X-User-ID names a persisted entity (ladder rung 3).
ENTITY_BACKED_ROLES = {"CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY", "CREW_LEAD", "VENDOR"}

# ---- enum member sets ------------------------------------------------------
# Ladder rung 6 names exactly these input fields and "no other field".
ENUMS = {
    "billing_mode": ["HOURLY", "PACKAGE"],
    "home_tier": ["STUDIO", "ONE_BED", "TWO_BED", "HOUSE"],
    "package_tier": ["STUDIO", "ONE_BED", "TWO_BED", "HOUSE"],
    "party_type": ["CLIENT", "FAMILY_MEMBER", "POA", "MOVE_MANAGER_STAFF"],
    "authority_scope": ["FULL", "DISPOSITION_ONLY", "BILLING_ONLY"],
    "unit_type": ["APARTMENT", "COTTAGE", "ASSISTED_LIVING_SUITE", "MEMORY_CARE_ROOM"],
    "room_type": ["LIVING", "BEDROOM", "KITCHEN", "DINING", "STORAGE", "BATH"],
    "category": ["FURNITURE", "ARTWORK", "JEWELRY", "APPLIANCE", "LINENS", "DOCUMENTS", "MISC"],
    "appraisal_source": ["NONE", "SELF_REPORTED", "APPRAISED"],
    "disposition": ["UNDECIDED", "KEEP", "DONATE", "SELL", "HAUL_AWAY"],
    "target_handling_state": [
        "AT_ORIGIN", "PACKED", "LOADED", "DELIVERED", "UNPACKED",
        "STAGED_FOR_PICKUP", "REMOVED",
    ],
    "entry_kind": ["LABOR", "TRAVEL", "BREAK"],
    "crew_role": ["LEAD", "ORGANIZER", "PACKER", "DRIVER"],
    "vendor_type": ["JUNK_HAUL", "CONSIGNMENT", "APPRAISAL", "CLEANING", "SHREDDING"],
    "service_kind": ["HAUL_AWAY", "CONSIGNMENT_PICKUP", "APPRAISAL", "CLEANING", "SHREDDING"],
    "line_type": [
        "PACKAGE_BASE", "HOURLY_LABOR", "OVERAGE_LABOR", "TRAVEL_SURCHARGE",
        "STAIRS_SURCHARGE", "LONG_CARRY_SURCHARGE", "VENDOR_PASSTHROUGH",
        "DISPOSAL_FEE", "CONSIGNMENT_CREDIT", "CONSIGNMENT_REVERSAL",
        "COORDINATION_FEE", "MANUAL_ADJUSTMENT",
    ],
    "priority": ["ESSENTIALS", "STANDARD"],
    "severity": ["CRITICAL", "MAJOR", "MINOR"],
    "resolution": ["KEEP", "RELEASE"],
    "milestone_key": ["ASSESSMENT", "SORT_PLAN", "PACK", "MOVE_DAY", "SETTLE_IN", "CLOSE_OUT"],
}

# ---- time / crew -----------------------------------------------------------
TIME_ROUNDING_INCREMENT_HOURS = "0.25"
HOURLY_MIN_CALLOUT_HOURS = "3.0"
HOURLY_OT_DAILY_THRESHOLD_HOURS = "8.0"
HOURLY_OT_MULTIPLIER = "1.5"

ROLE_RATE_CENTS = {
    "LEAD": 9500,
    "ORGANIZER": 8200,
    "PACKER": 6800,
    "DRIVER": 7400,
}

CREW_MIN_BY_HOME_TIER = {"STUDIO": 2, "ONE_BED": 3, "TWO_BED": 4, "HOUSE": 6}
CREW_LEAD_REQUIRED_COUNT = 1

# ---- package pipeline ------------------------------------------------------
PACKAGE_TIER_CENTS = {
    "STUDIO": 185000,
    "ONE_BED": 265000,
    "TWO_BED": 395000,
    "HOUSE": 620000,
}
PACKAGE_INCLUDED_HOURS = {"STUDIO": 18, "ONE_BED": 26, "TWO_BED": 40, "HOUSE": 64}
PACKAGE_OVERAGE_RATE_CENTS_PER_HOUR = 8900
PACKAGE_DEPOSIT_PCT_SIGNING = "0.30"
PACKAGE_DEPOSIT_PCT_PACK_START = "0.40"

# ---- surcharges ------------------------------------------------------------
TRAVEL_FREE_MILES = 15
TRAVEL_BAND1_MAX_MILES = 40
TRAVEL_BAND1_RATE_CENTS_PER_MILE = 317
TRAVEL_BAND2_RATE_CENTS_PER_MILE = 486

STAIRS_INCLUDED_FLIGHTS = 1
STAIRS_FEE_CENTS_PER_FLIGHT_PER_CREW = 2500

LONG_CARRY_FREE_FEET = 75
LONG_CARRY_FEE_CENTS_PER_25_FEET = 1800

# ---- trucks / rooms / volume ----------------------------------------------
TRUCK_PARTIAL_TRIP_THRESHOLD_PCT = "0.15"
PROVISIONAL_CAPACITY_FACTOR = "0.80"
APPROVED_CAPACITY_FACTOR = "1.00"
ROOM_VOLUME_SAFETY_FACTOR = "0.90"

ROOM_COUNT_BY_HOME_TIER = {"STUDIO": 2, "ONE_BED": 3, "TWO_BED": 5, "HOUSE": 8}
VOLUME_PER_ROOM_CFT = 180

# ---- dispositions / donation ----------------------------------------------
CONSIGN_MIN_VALUE_CENTS = 15000
DONATION_SELF_REPORT_FACTOR = "0.30"
DONATION_APPRAISED_FACTOR = "0.85"
DONATION_RECEIPT_CAP_CENTS = 500000

# ---- consignment -----------------------------------------------------------
MARKDOWN_ROUND_PCT = {0: "0", 1: "0.20", 2: "0.35"}
MAX_MARKDOWN_ROUNDS = 2
CONSIGN_UNSOLD_WINDOW_DAYS = 30

COMMISSION_BAND1_MAX_CENTS = 50000
COMMISSION_BAND2_MAX_CENTS = 250000
COMMISSION_BAND1_RATE = "0.50"
COMMISSION_BAND2_RATE = "0.40"
COMMISSION_BAND3_RATE = "0.30"

CONSIGN_PICKUP_FEE_CENTS = 7500
CONSIGN_PHOTO_FEE_CENTS_PER_ITEM = 1200
CONSIGN_PHOTO_FEE_CAP_CENTS = 12000

DISPOSAL_FEE_CENTS_PER_CFT = 145
DISPOSAL_MIN_FEE_CENTS = 9500
HAUL_MIN_LOAD_CFT = 250
HAUL_AUTO_QUOTE_CENTS = 45000

# ---- vendors ---------------------------------------------------------------
VENDOR_HOLDBACK_PCT_DEFAULT = "0.10"
VENDOR_DAILY_CAPACITY_DEFAULT = 3
SERVICE_KIND_TO_VENDOR_TYPE = {
    "HAUL_AWAY": "JUNK_HAUL",
    "CONSIGNMENT_PICKUP": "CONSIGNMENT",
    "APPRAISAL": "APPRAISAL",
    "CLEANING": "CLEANING",
    "SHREDDING": "SHREDDING",
}

# ---- invoice ---------------------------------------------------------------
COORD_FEE_PCT = "0.06"
COORD_FEE_TIER1_MAX_CENTS = 300000
COORD_FEE_TIER2_MAX_CENTS = 800000
COORD_FEE_TIER1_CAP_CENTS = 18000
COORD_FEE_TIER2_CAP_CENTS = 42000
COORD_FEE_TIER3_CAP_CENTS = 75000

SUBTOTAL_EXCLUDED_LINE_TYPES = {"COORDINATION_FEE", "CONSIGNMENT_CREDIT", "CONSIGNMENT_REVERSAL"}
CREDIT_LINE_TYPES = {"CONSIGNMENT_CREDIT", "CONSIGNMENT_REVERSAL"}

# ---- timeline --------------------------------------------------------------
MILESTONE_ORDER = ["ASSESSMENT", "SORT_PLAN", "PACK", "MOVE_DAY", "SETTLE_IN", "CLOSE_OUT"]
MILESTONE_OFFSET_DAYS = {
    "ASSESSMENT": -35,
    "SORT_PLAN": -21,
    "PACK": -3,
    "MOVE_DAY": 0,
    "SETTLE_IN": 7,
    "CLOSE_OUT": 21,
}
MILESTONE_WEIGHT = {
    "ASSESSMENT": 10,
    "SORT_PLAN": 25,
    "PACK": 15,
    "MOVE_DAY": 30,
    "SETTLE_IN": 15,
    "CLOSE_OUT": 5,
}

PUNCH_SLA_HOURS = {"CRITICAL": 24, "MAJOR": 72, "MINOR": 168}

MOVE_FREEZE_HOURS = 72

# ---- capped retries --------------------------------------------------------
MAX_MILESTONE_REOPENS = 2
MAX_PUNCH_REOPENS = 3
MAX_SORT_PLAN_REOPENS = 2
MAX_UNPACK_REOPENS = 2
MAX_MOVE_DAY_RESCHEDULES = 1
MAX_HOLD_ESCALATIONS = 2
MAX_INVOICE_RECALLS = 2
MAX_INVOICE_DISPUTES = 2
MAX_AUTHORITY_SUSPENSIONS = 2

# ---- authority -------------------------------------------------------------
AUTHORITY_DEFAULT_CEILING_CENTS = 100000
HIGH_VALUE_DISPOSITION_THRESHOLD_CENTS = 250000

CLOCK_EPOCH = "2026-05-01T00:00:00.000Z"
