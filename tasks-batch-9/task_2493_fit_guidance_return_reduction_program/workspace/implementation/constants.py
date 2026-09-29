"""Every literal constant declared by PRD.md / SCAFFOLD.yaml.

Nothing here is invented: each value traces to a sentence in the PRD or a
`constants:` block in the scaffold's calculation table.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1) and auth headers
# ---------------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLE_MERCH_OPS_ADMIN = "MerchOpsAdmin"
ROLE_VENDOR_USER = "VendorUser"
ROLE_FIT_ANALYST = "FitAnalyst"
ROLE_RETURNS_AUDITOR = "ReturnsAuditor"
ROLE_CUSTOMER = "Customer"

ALL_ROLES = (
    ROLE_MERCH_OPS_ADMIN,
    ROLE_VENDOR_USER,
    ROLE_FIT_ANALYST,
    ROLE_RETURNS_AUDITOR,
    ROLE_CUSTOMER,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
CATEGORY_CODES = ("TOPS", "BOTTOMS", "DRESSES", "OUTERWEAR", "FOOTWEAR")
SIZE_SYSTEMS = ("US_ALPHA", "US_NUMERIC", "EU", "UK")

LISTING_STATUSES = ("DRAFT", "LISTED", "SUSPENDED", "DELISTED")
FIT_READINESS_STATES = ("UNVERIFIED", "CHART_MAPPED", "GUIDANCE_READY")
FIT_WATCH_STATES = ("NORMAL", "WATCH", "CHRONIC")
DELIST_REASON_CODES = ("CHRONIC_FIT_RETURNS", "VENDOR_EXIT", "SEASONAL_END", "MANUAL")

SPEC_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "VERIFIED",
    "CORRECTION_REQUESTED",
    "REJECTED",
    "SUPERSEDED",
)
FABRIC_STRETCH_CLASSES = ("RIGID", "STRETCH", "HIGH_STRETCH")
MEASUREMENT_POINTS = ("CHEST", "WAIST", "HIP", "INSEAM")
CORRECTION_REASONS = ("GRADE_TOLERANCE_VIOLATION", "CHRONIC_FIT_RETURNS")

CHART_STATUSES = ("DRAFT", "STANDARDIZED", "RETIRED")
RETIRE_REASON_CODES = ("SUPERSEDED_BY_NEW_CHART", "VENDOR_SYSTEM_CHANGE", "DATA_QUALITY")

MAPPING_STATUSES = ("ACTIVE", "SUPERSEDED")
MAPPING_SUPERSEDED_REASONS = ("NEW_MAPPING", "CHART_RETIRED")

CUSTOMER_TIERS = ("STANDARD", "PLUS")
ABUSE_STATUSES = ("CLEAR", "WATCH", "RESTRICTED", "BLOCKED")
POLICY_CLASSES = ("STANDARD_WINDOW", "EXTENDED_WINDOW", "RESTRICTED_WINDOW")

ORDER_LINE_STATUSES = ("DELIVERED", "RETURN_IN_PROGRESS", "RETURNED", "KEPT")
PURCHASED_LINE_STATUSES = ("DELIVERED", "RETURN_IN_PROGRESS", "RETURNED", "KEPT")

REASON_CODES = (
    "FIT_TOO_SMALL",
    "FIT_TOO_LARGE",
    "QUALITY_DEFECT",
    "EXPECTATION_MISMATCH",
    "CHANGE_OF_MIND",
)
REASON_FAMILY_OF = {
    "FIT_TOO_SMALL": "FIT",
    "FIT_TOO_LARGE": "FIT",
    "QUALITY_DEFECT": "QUALITY",
    "EXPECTATION_MISMATCH": "EXPECTATION",
    "CHANGE_OF_MIND": "CHANGE_OF_MIND",
}
REASON_FAMILIES = ("FIT", "QUALITY", "EXPECTATION", "CHANGE_OF_MIND")

RETURN_CASE_STATUSES = (
    "TRIAGE",
    "FIT_REVIEW",
    "QUALITY_REVIEW",
    "EXPECTATION_REVIEW",
    "COOLING_OFF",
    "RESOLVED_REFUNDED",
    "RESOLVED_DENIED",
    "VOIDED",
)
REVIEW_BRANCH_STATUSES = (
    "FIT_REVIEW",
    "QUALITY_REVIEW",
    "EXPECTATION_REVIEW",
    "COOLING_OFF",
)
# statuses that count towards CustomerProfile.return_case_count (PRD 3.8)
LIVE_OR_CLOSED_CASE_STATUSES = (
    "TRIAGE",
    "FIT_REVIEW",
    "QUALITY_REVIEW",
    "EXPECTATION_REVIEW",
    "COOLING_OFF",
    "RESOLVED_REFUNDED",
    "RESOLVED_DENIED",
)
RESOLVED_CASE_STATUSES = ("RESOLVED_REFUNDED", "RESOLVED_DENIED")

ITEM_CONDITIONS = ("RESELLABLE_A", "RESELLABLE_B", "SALVAGE")
VOID_REASONS = ("AUDIT_REVERSAL", "DUPLICATE_CASE", "FRAUD_CONFIRMED")

COST_COMPONENTS = (
    "FREIGHT_INBOUND",
    "PROCESSING_LABOR",
    "REFURB_REPACK",
    "MARKDOWN_LOSS",
    "PAYMENT_FEE_UNRECOVERED",
    "VENDOR_CHARGEBACK_CREDIT",
)

FIT_VERDICTS = (
    "TOO_SMALL",
    "SLIGHTLY_SMALL",
    "TRUE_TO_SIZE",
    "SLIGHTLY_LARGE",
    "TOO_LARGE",
)
RETRACT_REASONS = ("AUTHOR_WITHDRAWN", "MODERATION_REMOVED")

POLICY_SCOPES = ("CATEGORY_DEFAULT", "CUSTOMER_OVERRIDE")

LEVERS = (
    "SIZE_CHART_STANDARDIZATION",
    "PDP_MODEL_MEASUREMENTS",
    "DETAIL_IMAGERY",
    "FIT_RECOMMENDATION_BADGE",
    "VENDOR_SPEC_CORRECTION",
)
READINESS_SENSITIVE_LEVERS = ("FIT_RECOMMENDATION_BADGE", "SIZE_CHART_STANDARDIZATION")

DEPLOYMENT_STATUSES = ("SCHEDULED", "ACTIVE", "TERMINATED", "MEASURED")
TERMINATED_REASON_CODES = (
    "WINDOW_ELAPSED",
    "ITEM_DELISTED",
    "MAPPING_SUPERSEDED",
    "MANUAL_STOP",
)
FUNDING_POSTURES = ("FUNDED", "UNDER_REVIEW", "DEFUNDED")
VENDOR_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")

SAVINGS_VARIANTS = ("deployment_attributed", "cohort_chronological")
DEFAULT_SAVINGS_VARIANT = "deployment_attributed"

# ---------------------------------------------------------------------------
# calculations.spec_grade_tolerance_verification
# ---------------------------------------------------------------------------
MEASUREMENT_POINT_ORDER = ("CHEST", "WAIST", "HIP", "INSEAM")
TOLERANCE_CEILING_MM = {"CHEST": 25, "WAIST": 25, "HIP": 25, "INSEAM": 20}
STRETCH_MULTIPLIER_PCT = {"RIGID": 100, "STRETCH": 150, "HIGH_STRETCH": 200}
MAX_CORRECTION_ROUNDS = 3
CORRECTION_COST_CENTS = 2500

# ---------------------------------------------------------------------------
# calculations.mapping_coverage
# ---------------------------------------------------------------------------
MIN_COVERAGE_BP = 8000
MIN_DETAIL_IMAGE_COUNT = 3

# ---------------------------------------------------------------------------
# calculations.return_refund_and_restocking_fee
# ---------------------------------------------------------------------------
RESTOCK_TIER_1_CENTS = 5000
RESTOCK_TIER_2_CENTS = 20000
ABUSE_FEE_MULTIPLIER_BP = 15000

# ---------------------------------------------------------------------------
# calculations.return_case_cost_postings
# ---------------------------------------------------------------------------
FREIGHT_INBOUND_CENTS = {
    "TOPS": 795,
    "BOTTOMS": 895,
    "DRESSES": 995,
    "OUTERWEAR": 1495,
    "FOOTWEAR": 1295,
}
LABOR_RATE_CENTS_PER_MIN = 62
HANDLING_MINUTES = {"FIT": 9, "QUALITY": 17, "EXPECTATION": 11, "CHANGE_OF_MIND": 7}
REFURB_PCT_BP = {"RESELLABLE_A": 150, "RESELLABLE_B": 400, "SALVAGE": 0}
MARKDOWN_PCT_BP = {"RESELLABLE_A": 0, "RESELLABLE_B": 1200, "SALVAGE": 6500}
PAYMENT_FEE_BP = 290
VENDOR_CHARGEBACK_PCT_BP = 4000

# ---------------------------------------------------------------------------
# calculations.item_chronic_return_score
# ---------------------------------------------------------------------------
FIT_WEIGHT_BP = 7500
EXPECTATION_WEIGHT_BP = 2500
WATCH_THRESHOLD_BP = 1500
CHRONIC_THRESHOLD_BP = 2500
MIN_FIT_RETURNS_WATCH = 1
MIN_FIT_RETURNS_CHRONIC = 2

# ---------------------------------------------------------------------------
# calculations.fit_recommendation
# ---------------------------------------------------------------------------
PERSONAL_SAMPLE_FLOOR = 3
CONFIDENCE_FLOOR_BP = 6000
VERDICT_OFFSET_CENTI = {
    "TOO_SMALL": 100,
    "SLIGHTLY_SMALL": 50,
    "TRUE_TO_SIZE": 0,
    "SLIGHTLY_LARGE": -50,
    "TOO_LARGE": -100,
}
FIT_RETURN_OFFSET_CENTI = {"FIT_TOO_SMALL": 100, "FIT_TOO_LARGE": -100}
FIT_RETURN_SIGNAL_WEIGHT = 200

# ---------------------------------------------------------------------------
# calculations.customer_abuse_and_policy_class
# ---------------------------------------------------------------------------
ABUSE_WINDOW_DAYS = 180
ABUSE_WATCH_STRIKES = 1
ABUSE_RESTRICTED_STRIKES = 2
ABUSE_BLOCKED_STRIKES = 3
ABUSE_RATE_BLOCK_BP = 7000
ABUSE_RATE_MIN_LINES = 4
POLICY_CLASS_DELTA_DAYS = {
    "STANDARD_WINDOW": 0,
    "EXTENDED_WINDOW": 30,
    "RESTRICTED_WINDOW": -15,
}
MIN_EFFECTIVE_WINDOW_DAYS = 7
ABUSE_STATUS_RANK = {"CLEAR": 0, "WATCH": 1, "RESTRICTED": 2, "BLOCKED": 3}

# ---------------------------------------------------------------------------
# calculations.deployment_window_rates / intervention_savings
# ---------------------------------------------------------------------------
SAVED_COST_PER_AVOIDED_RETURN_CENTS = {
    "TOPS": 3200,
    "BOTTOMS": 3600,
    "DRESSES": 4200,
    "OUTERWEAR": 5200,
    "FOOTWEAR": 4400,
}
FUNDING_TOLERANCE_CENTS = 5000

# ---------------------------------------------------------------------------
# calculations.vendor_reliability_score
# ---------------------------------------------------------------------------
QUALITY_CHARGEBACK_PENALTY_BP = 500
CORRECTION_ROUND_PENALTY_BP = 300
VENDOR_PROBATION_BP = 7000
VENDOR_SUSPEND_BP = 5000

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_EPOCH_ISO = "2026-08-01T00:00:00Z"
