"""Domain constants for the Outdoor Gear Repair & Warranty Program API.

Every value here is transcribed from PRD.md — the arithmetic constants from
the calculation sections (§2.6, §2.8, §2.9, §3.6, §3.7, §3.9), the enum
alphabets from the entity narratives (§3.1 - §3.9), and the envelope /
pagination facts from §2.2 - §2.3.
"""

# --------------------------------------------------------------------------
# Mount point and envelope (PRD §2.2, §2.3)
# --------------------------------------------------------------------------
API_PREFIX = "/gear-service"

DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# The instant every design scenario pins the clock to before building state.
SCENARIO_CLOCK_UTC = "2026-06-15T09:00:00Z"

# --------------------------------------------------------------------------
# Enum alphabets
# --------------------------------------------------------------------------
GEAR_CATEGORIES = (
    "SHELL_APPAREL",
    "INSULATION",
    "TENT_SHELTER",
    "PACK_HARNESS",
    "HARDGOODS_FRAME",
)
PARTS_SUPPORT_STATUSES = ("SUPPORTED", "SUBSTITUTION_ONLY", "NO_SUPPORT")
REPAIRABILITY_FLAGS = ("NONE", "WATCH", "REDESIGN_REQUESTED")

LOYALTY_TIERS = ("STANDARD", "PRO")
CONDITION_GRADES = ("A", "B", "C")
PROOF_TYPES = ("RECEIPT", "REGISTRATION", "RETAILER_LOOKUP", "NONE")

DISPOSITION_STATUSES = (
    "WITH_CUSTOMER",
    "AT_CENTER",
    "IN_REPAIR",
    "IRREPARABLE_HOLD",
    "RETURNED",
    "TRADED_IN",
    "REFURB_LISTED",
    "RESOLD",
    "RECYCLED",
)
WARRANTY_STATES = ("IN_WARRANTY", "EXPIRED", "LIFETIME")

INTAKE_KINDS = ("WARRANTY_CLAIM", "PAID_REPAIR_REQUEST")
DEFECT_TYPES = (
    "SEAM_FAILURE",
    "ZIPPER_FAILURE",
    "DELAMINATION",
    "FRAME_FRACTURE",
    "INSULATION_LOSS",
    "ABRASION_WEAR",
)
CLAIM_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "INFO_REQUESTED",
    "UNDER_ASSESSMENT",
    "WARRANTY_APPROVED",
    "REPLACEMENT_AUTHORIZED",
    "PAID_REPAIR_OFFERED",
    "WEAR_DENIED",
    "CLOSED_FULFILLED",
    "CLOSED_REPLACED",
    "CLOSED_DECLINED",
)
DETERMINATIONS = (
    "MANUFACTURING_DEFECT",
    "NORMAL_WEAR",
    "USER_DAMAGE",
    "INCONCLUSIVE",
)
DECISIONS = (
    "WARRANTY_REPAIR",
    "WARRANTY_REPLACE",
    "PAID_REPAIR_OFFERED",
    "WEAR_DENIED",
)

WORK_TYPES = ("FABRIC", "ZIPPER", "FRAME", "INSULATION")
TECHNICIAN_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")
WORK_BLOCK_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")

ORDER_KINDS = ("WARRANTY_REPAIR", "PAID_REPAIR")
WORK_STATUSES = (
    "QUEUED",
    "IN_WORK",
    "BENCH_DONE",
    "QC_PASSED",
    "RELEASED",
    "IRREPARABLE",
    "CLOSED_UNREPAIRED",
)
BILLING_STATUSES = (
    "NOT_BILLABLE",
    "ESTIMATE_PENDING",
    "ESTIMATE_SENT",
    "ESTIMATE_APPROVED",
    "ESTIMATE_DECLINED",
    "INVOICED",
    "PAID",
)
ESTIMATE_VARIANTS = ("PROVISIONAL", "FINAL")
ESTIMATE_STATUSES = (
    "SENT",
    "APPROVED",
    "DECLINED",
    "EXPIRED",
    "SUPERSEDED",
    "INVOICED",
    "PAID",
)

PART_KINDS = (
    "FABRIC_PANEL",
    "ZIPPER_SLIDER",
    "FRAME_SEGMENT",
    "INSULATION_FILL",
    "BUCKLE",
)
PART_LOT_STATUSES = ("AVAILABLE", "LOW", "DEPLETED")
RESERVATION_STATUSES = ("RESERVED", "CONSUMED", "RELEASED")

LIABILITY_BASES = ("REPAIR", "REPLACEMENT")
VALUATION_VARIANTS = ("DEPRECIATED_PURCHASE", "SUCCESSOR_MSRP")
LIABILITY_STATUSES = ("OPEN", "RELEASED")
RELEASE_REASONS = ("ORDER_RELEASED", "REVALUED_TO_REPLACEMENT", "CLAIM_CLOSED")

LIABILITY_POSTURES = ("OPEN", "CONSTRAINED", "FROZEN")

# --------------------------------------------------------------------------
# Valuation (PRD §2.8)
# --------------------------------------------------------------------------
DEPRECIATION_PER_YEAR = 0.10
DEPRECIATION_CAP = 0.60
RESIDUAL_FLOOR_PCT = 0.25
BRAND_COST_BASIS_PCT = 0.90

# --------------------------------------------------------------------------
# Repair-versus-replace threshold (PRD §3.5)
# --------------------------------------------------------------------------
CATEGORY_REPAIR_CAP_PCT = {
    "SHELL_APPAREL": 65,
    "INSULATION": 60,
    "TENT_SHELTER": 70,
    "PACK_HARNESS": 75,
    "HARDGOODS_FRAME": 55,
}
AGE_DECAY_PCT_PER_YEAR = 5
LIFETIME_BONUS_PCT = 10
THRESHOLD_FLOOR_PCT = 30
THRESHOLD_CEILING_PCT = 90

# --------------------------------------------------------------------------
# Pricing (PRD §3.7)
# --------------------------------------------------------------------------
LABOR_RATE_CENTS_PER_HOUR = {
    "FABRIC": 8500,
    "ZIPPER": 9500,
    "FRAME": 11000,
    "INSULATION": 9000,
}
SUPPLY_FEE_PCT = 0.07
SUPPLY_FEE_CAP_CENTS = 2500
LOYALTY_DISCOUNT_PCT = {"STANDARD": 0.00, "PRO": 0.10}
EXPEDITE_FEE_CENTS = 3500
TAX_PCT = 0.0825
ESTIMATE_VALIDITY_DAYS = 7

# --------------------------------------------------------------------------
# Turnaround commitment (PRD §3.6)
# --------------------------------------------------------------------------
CATEGORY_BASE_DAYS = {
    "SHELL_APPAREL": 10,
    "INSULATION": 14,
    "TENT_SHELTER": 12,
    "PACK_HARNESS": 9,
    "HARDGOODS_FRAME": 16,
}
WORK_TYPE_ADD_DAYS = {"FABRIC": 2, "ZIPPER": 3, "FRAME": 5, "INSULATION": 6}
PARTS_WAIT_DAYS = {"SUPPORTED": 0, "SUBSTITUTION_ONLY": 7, "NO_SUPPORT": 14}
SURGE_TIER_THRESHOLDS = ((9, 1.00), (24, 1.25), (49, 1.60))
SURGE_TIER_ABOVE = 2.00

# --------------------------------------------------------------------------
# Technician routing (PRD §3.4, §3.8)
# --------------------------------------------------------------------------
WORK_TYPE_MIN_LEVEL = {"FABRIC": 1, "ZIPPER": 2, "FRAME": 2, "INSULATION": 2}

# --------------------------------------------------------------------------
# Liability posture bands (PRD §2.9)
# --------------------------------------------------------------------------
CONSTRAINED_THRESHOLD_PCT = 60
FROZEN_THRESHOLD_PCT = 100

# --------------------------------------------------------------------------
# Trade-in and refurbished resale (PRD §3.9)
# --------------------------------------------------------------------------
TRADE_IN_PCT = {"A": 0.35, "B": 0.22, "C": 0.12}
GOODWILL_BONUS_CENTS = 5000
TRADE_IN_CAP_CENTS = 40000
REFURB_LIST_PCT = 0.55

# --------------------------------------------------------------------------
# Common-field inventory (PRD §2.5)
#
# Every entity carries id, created_at, updated_at and version, with a single
# documented exception: ClaimAssessment carries only id and created_at.
# --------------------------------------------------------------------------
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON_FIELDS = ("id", "created_at")
ENTITIES_WITHOUT_VERSION = ("ClaimAssessment",)
