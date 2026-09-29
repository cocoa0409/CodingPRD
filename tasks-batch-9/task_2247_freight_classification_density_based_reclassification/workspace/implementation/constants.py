"""Domain constants, taken verbatim from the PRD / scaffold constant tables."""
from decimal import Decimal

# ---- roles (PRD 2.1) -------------------------------------------------------
ROLES = (
    "PricingAnalyst",
    "TerminalOperator",
    "FreightInspector",
    "ClassificationAuditor",
    "DisputeReviewer",
    "Shipper",
)

# ---- classification codes (PRD 2.7) ---------------------------------------
CLASS_CODES = [
    Decimal(s)
    for s in (
        "50", "55", "60", "65", "70", "77.5", "85", "92.5", "100",
        "110", "125", "150", "175", "200", "250", "300", "400", "500",
    )
]
CLASS_CODE_SET = set(CLASS_CODES)

# ---- cube / density --------------------------------------------------------
CUBIC_INCHES_PER_CUBIC_FOOT = Decimal("1728")

# ---- characteristic floors (PRD 3.1) --------------------------------------
HANDLING_CODES = ("STANDARD", "FRAGILE", "HAZMAT", "OVERLENGTH")
STOWABILITY_CODES = ("STACKABLE", "NON_STACKABLE", "HAZ_SEGREGATED")
LIABILITY_CODES = ("LOW", "MEDIUM", "HIGH")

HANDLING_FLOOR = {
    "STANDARD": Decimal("0"),
    "FRAGILE": Decimal("100"),
    "HAZMAT": Decimal("125"),
    "OVERLENGTH": Decimal("110"),
}
STOWABILITY_FLOOR = {
    "STACKABLE": Decimal("0"),
    "NON_STACKABLE": Decimal("92.5"),
    "HAZ_SEGREGATED": Decimal("125"),
}
LIABILITY_FLOOR = {
    "LOW": Decimal("0"),
    "MEDIUM": Decimal("70"),
    "HIGH": Decimal("100"),
}

# ---- rating ----------------------------------------------------------------
WEIGHT_BREAK_FACTORS = [
    (Decimal("5000"), Decimal("0.78")),
    (Decimal("2000"), Decimal("0.88")),
    (Decimal("1000"), Decimal("1.00")),
    (Decimal("500"), Decimal("1.15")),
    (Decimal("0"), Decimal("1.30")),
]

VOLUME_TIER_DISCOUNTS = [
    (5000000, Decimal("0.12")),
    (2000000, Decimal("0.08")),
    (500000, Decimal("0.04")),
    (0, Decimal("0.00")),
]

MIGRATE_THRESHOLD = Decimal("0.05")
HOLD_THRESHOLD = Decimal("-0.05")
REPRICING_BUFFER_HOURS = 24

# ---- correction notice -----------------------------------------------------
RECLASS_FEE_CENTS = 4500
REWEIGH_FEE_CENTS = 2500
MIN_EVIDENCE_BUNDLE = 1
MIN_FINDING_PHOTOS = 2
MIN_DISPUTE_DOCS = 1

# ---- variance gate ---------------------------------------------------------
REWEIGH_VARIANCE_PCT = Decimal("2.00")
REWEIGH_MIN_ABS_LB = 10

# ---- liability index -------------------------------------------------------
ROLLING_WINDOW_DAYS = 90
DECAY_PER_DAY = Decimal("0.01")
DECAY_FLOOR = Decimal("0.25")
UPHELD_WEIGHT = Decimal("1.0")
PARTIAL_WEIGHT = Decimal("0.5")
TIER_1_MIN = Decimal("1.00")
TIER_2_MIN = Decimal("3.00")
TIER_3_MIN = Decimal("6.00")
BASE_DISPUTE_WINDOW_DAYS = 30
TIER_WINDOW_STEP_DAYS = 5
TIER_ORDINAL = {"TIER_0": 0, "TIER_1": 1, "TIER_2": 2, "TIER_3": 3}

# ---- dispute window --------------------------------------------------------
SUPPLEMENT_EXTENSION_DAYS = 7
MAX_SUPPLEMENT_REQUESTS = 2
MAX_DISPUTE_ROUNDS = 3

# ---- credit waterfall ------------------------------------------------------
INTEREST_RATE_PER_ROUND = Decimal("0.005")
INTEREST_CAP_CENTS = 250

# ---- status sets -----------------------------------------------------------
# PRD 2.9 conserved strike quantity
STRIKE_STATUSES = {
    "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED", "UPHELD", "PARTIALLY_OVERTURNED",
}
# PRD 2.9 shipment ledger identity
LEDGER_STATUSES = {
    "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED", "UPHELD",
    "PARTIALLY_OVERTURNED", "OVERTURNED",
}
# PRD 3.7 open notice cardinality
OPEN_NOTICE_STATUSES = {"DRAFT", "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED"}
# PRD 3.8 liability index contributors
INDEX_STATUSES = {"UPHELD", "PARTIALLY_OVERTURNED"}
# PRD 3.3 modelled shipment set
MODEL_BILLING_STATUSES = {"BILLED", "REBILLED", "CREDITED", "CLOSED"}

# ---- enums -----------------------------------------------------------------
BILLING_POSTURES = ("OPEN", "CREDIT_HOLD", "CLOSED")
EDUCATION_STATUSES = ("NONE", "REQUIRED", "COMPLETED")
TARIFF_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
CLASSIFICATION_BASES = ("DENSITY_BASED", "FIXED_CLASS")
PROGRAM_TYPES = ("CLASS_BASED", "DENSITY_BASED", "FAK")
PROGRAM_STATUSES = ("MODELING", "APPROVED", "ACTIVE", "RETIRED")
AGREEMENT_TYPES = ("EXCEPTION_CLASS", "FAK")
AGREEMENT_STATUSES = ("PENDING", "ACTIVE")
CLASS_STATUSES = (
    "DECLARED", "CAPTURED", "UNDER_INSPECTION", "RECLASS_PENDING",
    "RECLASSED", "CLASS_CONFIRMED",
)
BILLING_STATUSES = ("UNBILLED", "BILLED", "REBILLED", "CREDITED", "CLOSED")
DEVICE_TYPES = ("DIMENSIONER", "SCALE", "COMBINED")
FINDING_BASES = ("DENSITY", "STOWABILITY", "HANDLING", "LIABILITY", "COMMODITY_MISMATCH")
FINDING_STATUSES = ("RECORDED", "ACCEPTED", "SUPERSEDED")
NOTICE_TYPES = ("REWEIGH", "RECLASS", "BOTH")
NOTICE_STATUSES = (
    "DRAFT", "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED", "UPHELD",
    "PARTIALLY_OVERTURNED", "OVERTURNED", "VOID",
)
CLAIM_BASES = ("DENSITY_RECOMPUTE", "EXCEPTION_AGREEMENT", "DEVICE_CALIBRATION", "EVIDENCE_INSUFFICIENT")
DISPUTE_STATUSES = ("OPEN", "SUPPLEMENT_REQUESTED", "SUPPLEMENTED", "RESOLVED")
OUTCOMES = ("UPHELD_CARRIER", "PARTIAL", "OVERTURNED")
REPRICING_SCOPES = ("ALL_CLASS_BASED", "ALL_DENSITY_BASED", "ALL_ACTIVE")
REPRICING_STATUSES = ("DRAFT", "MODELED", "COMMITTED")
CLASSIFICATION_SOURCES = (
    "BOL_DECLARED", "FIXED_CLASS", "DIMENSIONER", "INSPECTION",
    "EXCEPTION_AGREEMENT", "FAK",
)
