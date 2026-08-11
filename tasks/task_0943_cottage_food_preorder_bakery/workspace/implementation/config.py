"""Declared constants for the cottage-food pre-order bakery API.

Every value here traces to SCAFFOLD.yaml `global_constants` or to a figure
stated literally in PRD.md.  Nothing in this module is derived from the wall
clock or from any environment other than PORT (handled in app.py).
"""

API_PREFIX = "/bakery"

# ---- clock -----------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# ---- offer window / cutoff -------------------------------------------------
HOLD_TTL_MINUTES = 45
CUTOFF_BOUNDARY_SEMANTICS = "strict_exclusive"
CUTOFF_EXTENSION_MAX_COUNT = 1
CUTOFF_EXTENSION_MINUTES = 120
WINDOW_UNIT_CAPACITY_DEFAULT = 240
WINDOW_BATCH_SLOT_CAPACITY_DEFAULT = 12
WINDOW_OVEN_HOURS_CAPACITY_DEFAULT = 18.0
CAPACITY_CONSTRAINED_UTILIZATION_PCT = 0.80

# ---- batching / production -------------------------------------------------
BATCH_SLOT_UNITS = 24
OVEN_HOURS_PER_BATCH_SLOT = 1.5
OVEN_HOURS_PRECISION_DECIMALS = 2
DEFAULT_YIELD_UNITS_PER_SLOT = 24
SHORTFALL_CREDIT_MULTIPLIER = "1.00"

# ---- pricing ---------------------------------------------------------------
DOZEN_SIZE = 12
BAKERS_DOZEN_UNITS = 13
MIN_UNITS_PER_LINE = 1
MAX_UNITS_PER_LINE = 120
MAX_LINES_PER_ORDER = 12
TAX_RATE_BPS = 725
TAX_ROUNDING_ORDER = "per_line_then_sum"

# ---- cottage-food statutory ------------------------------------------------
ANNUAL_GROSS_SALES_CAP_CENTS = 8500000
TIP_COUNTS_TOWARD_GROSS_CAP = False
DTC_ELIGIBLE_PRODUCT_CLASS = "SHELF_STABLE"
PERMITTED_DELIVERY_RADIUS_KM = 40.0
WHOLESALE_PERMITTED = False

# ---- allergen --------------------------------------------------------------
ALLERGEN_TREE_MAX_DEPTH = 5
ALLERGEN_SEVERITY_HARD_BLOCK = "ANAPHYLACTIC"
ALLERGEN_SEVERITY_ACK_REQUIRED = "INTOLERANCE"
CROSS_CONTACT_ADVISORY_TEXT = (
    "Made in a home kitchen that also handles wheat, egg, milk, soy, "
    "peanut and tree nuts."
)
COTTAGE_FOOD_STATEMENT_TEXT = (
    "Made in a home kitchen that is not subject to routine state inspection."
)

# ---- handoff ---------------------------------------------------------------
PICKUP_GRACE_MINUTES = 90
MISSED_REBOOK_MAX = 1
FORFEIT_REFUND_PCT = "0.00"
DELIVERY_MINIMUM_CENTS = 3500
DELIVERY_ZONE_TIER1_MAX_KM = 8.0
DELIVERY_ZONE_TIER2_MAX_KM = 20.0
DELIVERY_ZONE_TIER3_MAX_KM = 40.0
DELIVERY_FEE_TIER1_CENTS = 500
DELIVERY_FEE_TIER2_CENTS = 900
DELIVERY_FEE_TIER3_CENTS = 1400

# ---- subscription ----------------------------------------------------------
SKIP_DEADLINE_HOURS_BEFORE_CUTOFF = 24
SUBSCRIPTION_PAUSE_CAP_COUNT = 2
SUBSCRIPTION_RESERVE_UNIT_SHARE_PCT = "0.30"
PREPAID_CYCLE_DISCOUNT_PCT = "0.10"
PREPAID_DEPOSIT_CYCLES = 4
PAST_DUE_GRACE_HOURS = 72

# ---- payment / money -------------------------------------------------------
TIP_PCT_MAX = "0.30"
TIP_FIXED_MAX_CENTS = 5000
CREDIT_EXPIRY_DAYS = 365
PAYOUT_PERIOD_DAYS = 14

# ---- review ----------------------------------------------------------------
REVIEW_WINDOW_DAYS = 21
BAKER_RESPONSE_WINDOW_DAYS = 14
RATING_ROLLUP_MIN_REVIEWS = 3
RATING_SCALE_MIN = 1
RATING_SCALE_MAX = 5
RATING_AVG_PRECISION_DECIMALS = 2

# ---- cascade ---------------------------------------------------------------
RECALL_CASCADE_MAX_DEPTH = 6

# ---- pagination ------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ---- roles -----------------------------------------------------------------
ROLE_BAKER = "Baker"
ROLE_CUSTOMER = "Customer"
ROLE_ADMIN = "PlatformAdmin"
ROLE_INSPECTOR = "HealthInspector"
ALL_ROLES = (ROLE_BAKER, ROLE_CUSTOMER, ROLE_ADMIN, ROLE_INSPECTOR)

# ---- enum value sets (PRD 2.12) -------------------------------------------
ENUM_SETS = {
    "permit_status": ("PENDING", "ACTIVE", "SUSPENDED", "CAP_REACHED"),
    "recipe_status": ("DRAFT", "PUBLISHED", "REVISING", "RETIRED"),
    "lot_status": ("RECEIVED", "RELEASED", "CONSUMED", "RECALLED", "EXPIRED"),
    "listing_status": ("DRAFT", "LISTED", "PAUSED", "DELISTED"),
    "window_status": (
        "DRAFT", "OPEN", "LOCKED", "IN_PRODUCTION", "HANDOFF_OPEN",
        "CLOSED", "CANCELLED",
    ),
    "plan_status": ("UNPLANNED", "PLANNED", "RECONCILED"),
    "capacity_posture": ("OPEN_CAPACITY", "CONSTRAINED", "EXHAUSTED"),
    "order_status": (
        "DRAFT", "PENDING_HOLD", "EXPIRED_HOLD", "CONFIRMED", "IN_PRODUCTION",
        "READY", "FULFILLED", "FORFEITED", "CANCELLED", "VOIDED_RECALL",
    ),
    "payment_status": (
        "UNPAID", "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED",
        "VOIDED",
    ),
    "handoff_status": (
        "NOT_SCHEDULED", "SCHEDULED", "PICKUP_READY", "OUT_FOR_DELIVERY",
        "HANDED_OFF", "MISSED", "FORFEITED",
    ),
    "line_status": (
        "PENDING", "RELEASED", "ALLOCATED", "FULFILLED", "SHORTED",
        "CREDITED", "RECALL_VOID",
    ),
    "batch_status": (
        "PLANNED", "MIXED", "BAKED", "YIELD_CONFIRMED", "UNDER_YIELD",
        "ALLOCATED", "CLOSED", "SCRAPPED_RECALL",
    ),
    "label_status": ("ISSUED", "SUPERSEDED", "VOID", "CONSUMED"),
    "sub_status": ("PENDING", "ACTIVE", "PAUSED", "PAST_DUE", "CANCELLED"),
    "cycle_status": (
        "GENERATED", "RESERVED", "CONFIRMED", "SKIPPED", "RELEASED",
        "ORDER_PLACED",
    ),
    "payment_state": (
        "INITIATED", "AUTHORIZED", "CAPTURED", "SETTLED", "DECLINED", "VOIDED",
    ),
    "route_status": ("DRAFT", "SEQUENCED", "DISPATCHED", "COMPLETED"),
    "review_status": ("SUBMITTED", "RESPONDED", "HIDDEN"),
    # non-lifecycle enumerated fields
    "channel": ("DTC", "WHOLESALE"),
    "handoff_mode": ("PICKUP_COUNTER", "PORCH_SELF_SERVE", "DELIVERY"),
    "source": ("WALKUP", "SUBSCRIPTION_CLUB"),
    "disposition": ("WHOLE_UNHEATED", "WITH_UTENSILS", "BY_THE_SLICE", "HEATED"),
    "product_class": ("SHELF_STABLE", "REFRIGERATION_REQUIRED"),
    "pricing_basis": ("PER_UNIT", "PER_DOZEN_BAKERS"),
    "oven_profile": ("STANDARD", "LONG_BAKE"),
    "cadence": ("WEEKLY", "BIWEEKLY", "MONTHLY"),
    "billing_mode": ("PREPAID", "PAY_PER_CYCLE"),
    "tip_mode": ("PERCENT", "FIXED"),
    "outcome": ("SUCCEEDED", "DECLINED"),
    "ledger_scope": ("CUSTOMER_CREDIT", "SUBSCRIPTION_PREPAID", "SETTLEMENT"),
    "movement_kind": ("REFUND", "SHORTFALL_CREDIT", "PREPAY_DEPOSIT",
                      "CREDIT_REDEEM"),
    "reason": ("SHORTFALL", "RECALL_VOID", "CUSTOMER_CANCEL",
               "SUBSCRIPTION_PREPAY", "ORDER_APPLY"),
    "severity": ("ANAPHYLACTIC", "INTOLERANCE"),
    # composite target sets used by *_status / advance style endpoints
    "handoff_outcome": ("HANDED_OFF", "MISSED", "FORFEITED"),
    "plan_mode": ("PLAN", "REPLAN"),
}
