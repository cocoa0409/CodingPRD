"""Pinned domain constants (PRD sections 3.1-3.9, SCAFFOLD calculations)."""

from decimal import Decimal

# ---- roles -----------------------------------------------------------------
ROLES = (
    "ProductEngineer",
    "ComplianceOfficer",
    "OrderPlanner",
    "FacilityManager",
    "ServicePartnerTech",
    "ServiceOpsAdmin",
)

ANY_ROLE = ROLES

# ---- enumerations ----------------------------------------------------------
CATEGORIES = ("CARDIO", "STRENGTH", "CONNECTED")
DUTY_CLASSES = ("LIGHT_COMMERCIAL", "FULL_COMMERCIAL", "INSTITUTIONAL")
FINISH_CODES = (
    "GRAPHITE",
    "ARCTIC_WHITE",
    "CLUB_RED",
    "CUSTOM_BRAND_DECAL",
    "PREMIUM_UPHOLSTERY",
)
CONSOLE_PLATFORMS = ("CONSOLE_T1", "CONSOLE_T2", "CONSOLE_X")
MODEL_LIFECYCLE = ("PRE_RELEASE", "ACTIVE", "SUNSET", "OBSOLETE")
REVISION_STATUSES = (
    "DRAFT",
    "IN_TESTING",
    "TEST_FAILED",
    "QUALIFIED",
    "RELEASED",
    "SUNSET_ANNOUNCED",
    "OBSOLETE",
    "SUPERSEDED",
)
RUN_STATUSES = ("RESERVED", "RUNNING", "COMPLETED", "ABORTED")
RUN_OUTCOMES = ("PENDING", "PASSED", "FAILED")
COMPLETION_OUTCOMES = ("PASSED", "FAILED")
FIRMWARE_STATUSES = ("ACTIVE", "WITHDRAWN")
CERT_STATUSES = ("SUBMITTED", "CERTIFIED", "REJECTED", "REVOKED")
FREIGHT_ZONES = ("Z1", "Z2", "Z3", "Z4")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
FACILITY_STATUSES = ("ACTIVE", "SUSPENDED")
CONFIG_STATUSES = ("CONFIGURING", "CONFIRMED")
FULFILLMENT_STATUSES = ("PENDING", "IN_PRODUCTION", "STAGED", "INSTALLING", "INSTALLED")
BILLING_STATUSES = ("UNQUOTED", "QUOTED", "INVOICED", "SETTLED")
PRICE_VARIANTS = ("NONE", "PROVISIONAL", "FINAL")
LINE_STATUSES = ("ACTIVE", "VOIDED")
REGIONS = ("R_NORTH", "R_SOUTH", "R_EAST", "R_WEST")
PARTNER_COVERAGE = ("ACTIVE", "OVER_COMMITTED")
INSTALL_JOB_STATUSES = ("SCHEDULED", "ON_SITE", "PUNCH_LIST", "COMPLETED", "ABORTED")
INSTALL_JOB_OPEN = ("SCHEDULED", "ON_SITE", "PUNCH_LIST")
ASSET_STATUSES = (
    "BUILT",
    "IN_SERVICE",
    "TRADE_IN_RETURNED",
    "REFURB_INTAKE",
    "REFURB_CERTIFIED",
    "RESOLD",
    "SCRAPPED",
)
CONNECTIVITY_STATUSES = (
    "NOT_APPLICABLE",
    "SUPPORTED",
    "SUNSET_TRACKED",
    "SUPPORT_GAP",
    "FIRMWARE_REVOKED",
)
GRADES = ("A", "B", "C")
PM_STATUSES = ("DRAFT", "ACTIVE", "NEEDS_REVISION", "TERMINATED")
PM_TIERS = ("BASIC", "PRO", "PLATINUM")
NEEDS_REVISION_REASONS = ("CONSOLE_SUPPORT_LOST", "FIRMWARE_REVOKED")
VISIT_STATUSES = ("SCHEDULED", "ON_HOLD", "COMPLETED", "CANCELLED")

# ---- durability / qualification -------------------------------------------
DUTY_MIN_CYCLES = {
    "LIGHT_COMMERCIAL": 250000,
    "FULL_COMMERCIAL": 500000,
    "INSTITUTIONAL": 900000,
}
RUNNING_PROJECTION_FACTOR = Decimal("0.8")
FAILURE_CREDIT_FACTOR = Decimal("0.5")
REWORK_LIMIT = 3
SUPERSEDE_CHAIN_MAX_DEPTH = 5

# ---- pricing ---------------------------------------------------------------
FINISH_SURCHARGE_CENTS = {
    "GRAPHITE": 0,
    "ARCTIC_WHITE": 4500,
    "CLUB_RED": 7500,
    "CUSTOM_BRAND_DECAL": 12000,
    "PREMIUM_UPHOLSTERY": 26000,
}
DUTY_UPLIFT_PCT = {
    "LIGHT_COMMERCIAL": Decimal("0.00"),
    "FULL_COMMERCIAL": Decimal("0.06"),
    "INSTITUTIONAL": Decimal("0.11"),
}
INSTALL_HOURS_PER_UNIT = {
    "CARDIO": Decimal("1.5"),
    "STRENGTH": Decimal("2.5"),
    "CONNECTED": Decimal("3.0"),
}
INSTALL_LABOR_RATE_CENTS = Decimal("8875")
VOLUME_DISCOUNT_TIERS = (
    (0, 5000000, Decimal("0.00")),
    (5000000, 15000000, Decimal("0.04")),
    (15000000, 40000000, Decimal("0.075")),
    (40000000, None, Decimal("0.11")),
)
FREE_FREIGHT_THRESHOLD_CENTS = 20000000
FREIGHT_RATE_CENTS_PER_KG = {
    "Z1": Decimal("180"),
    "Z2": Decimal("260"),
    "Z3": Decimal("340"),
    "Z4": Decimal("520"),
}
PUNCH_LIST_CREDIT_CENTS = 25000

# ---- preventive maintenance ------------------------------------------------
PM_BASE_HOURS = {
    "CARDIO": Decimal("1.0"),
    "STRENGTH": Decimal("0.6"),
    "CONNECTED": Decimal("1.4"),
}
USAGE_NORM_HOURS = Decimal("2000")
TIER_MULTIPLIER = {
    "BASIC": Decimal("1.0"),
    "PRO": Decimal("1.25"),
    "PLATINUM": Decimal("1.6"),
}

# ---- support windows -------------------------------------------------------
WARRANTY_DAYS = {
    "LIGHT_COMMERCIAL": 365,
    "FULL_COMMERCIAL": 1095,
    "INSTITUTIONAL": 1825,
}
FIRMWARE_SUPPORT_COMMITMENT_DAYS = 1825

# ---- trade-in valuation ----------------------------------------------------
RESIDUAL_BASE = Decimal("0.55")
AGE_DECAY_PER_YEAR = Decimal("0.08")
SERVICE_PENALTY_PER_VISIT = Decimal("0.015")
RESIDUAL_FLOOR = Decimal("0.10")
CONDITION_MULT = {"A": Decimal("1.0"), "B": Decimal("0.85"), "C": Decimal("0.65")}
UNSUPPORTED_CONSOLE_MULT = Decimal("0.75")

# ---- installation ----------------------------------------------------------
INSTALL_TRAVEL_BUFFER_MINUTES = 120

DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
