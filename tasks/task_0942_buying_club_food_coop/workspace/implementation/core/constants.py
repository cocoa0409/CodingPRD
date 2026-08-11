"""Global constants — every tunable named in the PRD/SCAFFOLD, with its value."""

# --- clock -------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# --- minimums ----------------------------------------------------------------
DROP_MINIMUM_DEFAULT_CENTS = 50000
ROUTE_MINIMUM_DEFAULT_CENTS = 250000
ROUTE_REEFER_SLOTS_DEFAULT = 2
ROUTE_MAX_PALLETS_DEFAULT = 12

# --- split-case pricing ------------------------------------------------------
SPLIT_CASE_FEE_PCT = "0.12"
SPLIT_CASE_FEE_MIN_CENTS = 25

# --- pre-order cycle windows -------------------------------------------------
EXCEPTION_WINDOW_HOURS = 48
ROUTE_TURNAROUND_HOURS = 48

# --- substitution ------------------------------------------------------------
SUBSTITUTION_TOLERANCE_PCT = "0.10"
SUBSTITUTION_RESPONSE_HOURS = 24

# --- two-phase payment -------------------------------------------------------
PAYMENT_AUTH_BUFFER_PCT = "0.10"
PAYMENT_VARIANCE_TOLERANCE_PCT = "0.15"
PAYMENT_VARIANCE_TOLERANCE_FLOOR_CENTS = 500

# --- reconciliation ----------------------------------------------------------
RECON_VARIANCE_TOLERANCE_CENTS = 200

# --- cold chain / pallets ----------------------------------------------------
REEFER_SURCHARGE_CENTS_PER_SLOT = 4500
PALLET_MAX_WEIGHT_GRAMS = 900000
PALLET_MAX_CUBE_CM3 = 1600000
REEFER_REQUIRED_TEMP_CLASSES = ("FROZEN", "CHILLED")

# --- coordinator commission --------------------------------------------------
COMMISSION_BAND_1_MAX_CENTS = 100000
COMMISSION_BAND_1_RATE = "0.03"
COMMISSION_BAND_2_MAX_CENTS = 300000
COMMISSION_BAND_2_RATE = "0.05"
COMMISSION_BAND_3_RATE = "0.07"
COMMISSION_VOLUNTEER_MIN_HOURS = "4.0"
COMMISSION_VOLUNTEER_UNMET_MULTIPLIER = "0.50"
COMMISSION_STORE_CREDIT_BONUS_PCT = "0.10"
COMMISSION_CASH_FEE_PCT = "0.02"
COMMISSION_CASH_FEE_MIN_CENTS = 100

# --- membership --------------------------------------------------------------
COORDINATOR_MIN_TIER_RANK = 2
MEMBERSHIP_TERM_DAYS = 365
DUES_GRACE_DAYS = 14

TIER_RANK = {"BASIC": 1, "PLUS": 2, "PRO": 3}
TIER_ANNUAL_DUES_CENTS = {"BASIC": 3000, "PLUS": 9000, "PRO": 18000}
TIER_DISCOUNT_PCT = {"BASIC": "0.00", "PLUS": "0.05", "PRO": "0.09"}

# --- volunteer credits -------------------------------------------------------
VOLUNTEER_CREDIT_CENTS_PER_HOUR = 1200
VOLUNTEER_CREDIT_EXPIRY_DAYS = 180
CREDIT_MAX_OFFSET_PCT = "0.50"

# --- ordering / rollover -----------------------------------------------------
MAX_ORDER_LINE_UNITS = 500
MIN_ORDER_LINE_UNITS = 1
ROLLFORWARD_MAX_PER_DROP_RUN = 1
ROLLOVER_PRICE_POLICY = "NEW_CYCLE_PRICE"

# --- pagination --------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- roles -------------------------------------------------------------------
ROLES = ("ClubAdmin", "DropCoordinator", "Member", "WarehouseOperator", "FinanceOfficer")

# --- enum member lists -------------------------------------------------------
TIERS = ("BASIC", "PLUS", "PRO")
MEMBER_STATUSES = ("PENDING", "ACTIVE", "LAPSED")
TEMP_CLASSES = ("FROZEN", "CHILLED", "DRY")
REMAINDER_POLICIES = ("SHORT_FILL", "ROUND_UP", "DROP")
ITEM_STATUSES = ("ACTIVE", "DISCONTINUED")
CYCLE_STATUSES = ("OPEN", "LOCKED", "SUBMITTED", "RECEIVED", "CONSOLIDATED",
                  "DELIVERED", "RECONCILED", "CLOSED", "CANCELLED")
EXCEPTION_STATES = ("NOT_STARTED", "OPEN", "CLOSED")
ROUTE_RUN_STATUSES = ("PLANNED", "QUALIFIED", "DEFERRED", "SUBMITTED", "RECEIVED",
                      "CONSOLIDATED", "DELIVERED")
DROP_RUN_STATUSES = ("OPEN", "QUALIFIED", "MERGED", "DEFERRED", "ROLLED_FORWARD",
                     "SUBMITTED", "RECEIVED", "SETTLED", "CANCELLED")
ORDER_STATUSES = ("DRAFT", "SUBMITTED", "LOCKED", "FILLED", "SHORT_FILLED",
                  "DELIVERED", "CLOSED", "CANCELLED")
PAYMENT_STATUSES = ("UNPAID", "AUTHORIZED", "AUTH_FAILED", "CAPTURED",
                    "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED")
LINE_STATUSES = ("REQUESTED", "CONFIRMED", "FILLED", "SHORT_FILLED", "SUBSTITUTED",
                 "DROPPED", "ROLLED_FORWARD", "CANCELLED")
SUBSTITUTION_PREFS = ("NONE", "ANY_SUBSTITUTE", "APPROVAL_REQUIRED")
OFFER_STATUSES = ("PENDING", "APPROVED", "DECLINED", "AUTO_APPROVED", "AUTO_DECLINED")
PALLET_STATUSES = ("BUILDING", "SEALED", "DELIVERED")
PAYMENT_KINDS = ("AUTHORIZATION", "CAPTURE", "REFUND")
PAYMENT_METHODS = ("CARD", "STORE_CREDIT")
PAYMENT_RECORD_STATUSES = ("SUCCEEDED", "FAILED", "VOIDED")
RECON_STATUSES = ("DRAFT", "BALANCED", "VARIANCE_HELD", "POSTED", "VOID")
ACCRUAL_STATUSES = ("ACCRUED", "ADJUSTED", "PAID")
PAYOUT_MODES = ("STORE_CREDIT", "CASH")
SHIFT_STATUSES = ("LOGGED", "VERIFIED", "REJECTED")
CREDIT_SOURCES = ("VOLUNTEER", "REFUND", "COMMISSION", "ADJUSTMENT")
CREDIT_STATUSES = ("ACTIVE", "PARTIALLY_CONSUMED", "CONSUMED", "EXPIRED")
REFUND_DESTINATIONS = ("CARD", "STORE_CREDIT")
SIMULATED_OUTCOMES = ("SUCCEEDED", "FAILED")
