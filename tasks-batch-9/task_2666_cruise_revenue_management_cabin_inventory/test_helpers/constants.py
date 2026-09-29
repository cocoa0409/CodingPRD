"""
Business constants and enum vocabularies pinned by the PRD.

Every value here is quoted from the PRD prose so the tests never re-derive a
threshold from a magic literal buried in an assertion.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.2)
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Fare buildup (PRD §3.4)
# --------------------------------------------------------------------------
SINGLE_SUPPLEMENT_MULT = 1.75
BERTH_TIER_1_FLOOR_CENTS = 250000
BERTH_TIER_1_PCT = 0.10
BERTH_TIER_2_FLOOR_CENTS = 400000
BERTH_TIER_2_PCT = 0.20
BERTH_TIER_3_FLOOR_CENTS = 600000
BERTH_TIER_3_PCT = 0.30
DEPOSIT_PCT = 0.20
DEPOSIT_MIN_PER_GUEST_CENTS = 25000

# --------------------------------------------------------------------------
# Cancellation penalty bands (PRD §3.6)
# --------------------------------------------------------------------------
PENALTY_FREE_DAYS = 120
PENALTY_T1_DAYS = 90
PENALTY_T1_PCT = 0.25
PENALTY_T2_DAYS = 60
PENALTY_T2_PCT = 0.50
PENALTY_T3_DAYS = 30
PENALTY_T3_PCT = 0.75
DELINQUENCY_GRACE_DAYS = 7

# --------------------------------------------------------------------------
# Oversell (PRD §2.7)
# --------------------------------------------------------------------------
OVERSELL_PCT_CAP = 0.10

# --------------------------------------------------------------------------
# Group block review (PRD §3.3)
# --------------------------------------------------------------------------
ATTRITION_RETAIN_PCT = 0.5
REVIEW_EXTENSION_DAYS = 14
MAX_REVIEW_EXTENSIONS = 2

# --------------------------------------------------------------------------
# Upgrade bidding (PRD §3.7)
# --------------------------------------------------------------------------
BID_FLOOR_PCT = 0.40
BID_WINDOW_MIN_DAYS = 3
BID_WINDOW_MAX_DAYS = 60
MAX_COUNTER_ROUNDS = 2

# --------------------------------------------------------------------------
# Inventory posture (PRD §2.11)
# --------------------------------------------------------------------------
POSTURE_RESTRICTED_PCT = 90.00
POSTURE_FROZEN_PCT = 100.00

# --------------------------------------------------------------------------
# Loyalty tiers (PRD §3.1)
# --------------------------------------------------------------------------
MEMBER_FLOOR = 1
MEMBER_PCT = 0.00
GOLD_FLOOR = 3
GOLD_PCT = 0.03
PLATINUM_FLOOR = 6
PLATINUM_PCT = 0.05

# --------------------------------------------------------------------------
# Itinerary compensation (PRD §3.8)
# --------------------------------------------------------------------------
OBC_LOW_PER_GUEST_CENTS = 2500
OBC_HIGH_PER_GUEST_CENTS = 5000
REFUND_PCT_PORT = 0.05
REFUND_PCT_SHORTENED = 0.10

# --------------------------------------------------------------------------
# RALBD (PRD §3.9)
# --------------------------------------------------------------------------
RALBD_ALERT_FLOOR_CENTS = 20000

# --------------------------------------------------------------------------
# Bounded cycles / cadence (PRD §2.10, §3.2)
# --------------------------------------------------------------------------
MAX_SALES_SUSPENSIONS = 2
PROMO_CADENCE_GAP_DAYS = 7

# --------------------------------------------------------------------------
# Enum vocabularies
# --------------------------------------------------------------------------
SAILING_STATUSES = (
    "PLANNED",
    "OPEN_FOR_SALE",
    "SALES_SUSPENDED",
    "INVENTORY_CLOSED",
    "SAILED",
)
INVENTORY_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
BOOKING_STATUSES = ("WAITLISTED", "OPTION", "CONFIRMED", "SAILED", "CANCELLED")
PAYMENT_STATUSES = (
    "AWAITING_DEPOSIT",
    "DEPOSIT_PAID",
    "PAID_IN_FULL",
    "DELINQUENT",
    "PENALTY_ASSESSED",
    "REFUNDED",
)
PAYMENT_TERMS = ("STANDARD", "FULL_AT_BOOKING")
PAYMENT_KINDS = ("DEPOSIT", "FINAL_PAYMENT", "PARTIAL", "UPGRADE_CHARGE", "REFUND")
PROMOTION_STATUSES = ("SCHEDULED", "ACTIVE", "EXHAUSTED", "EXPIRED", "WITHDRAWN")
PROMOTION_AUDIENCES = ("GENERAL", "REPEAT_GUEST", "GROUP")
GROUP_BLOCK_STATUSES = ("TENTATIVE", "DEFINITE", "PARTIALLY_RELEASED", "RELEASED")
RELEASE_POLICIES = ("FULL_RELEASE", "ATTRITION_50")
BID_STATUSES = ("SUBMITTED", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED")
ITINERARY_KINDS = ("PORT_CANCELLED", "PORT_SUBSTITUTED", "ITINERARY_SHORTENED")
COMPENSATION_POLICIES = ("OBC_ONLY", "OBC_PLUS_REFUND_PCT")
LOYALTY_TIERS = ("NONE", "MEMBER", "GOLD", "PLATINUM")

# Reserved server-driven cancellation reasons (PRD §3.6)
CANCEL_REASON_INVENTORY_CLOSED = "INVENTORY_CLOSED"
CANCEL_REASON_SAILED_UNCONFIRMED = "SAILED_UNCONFIRMED"
CANCEL_REASON_AUTO_DELINQUENT = "AUTO_DELINQUENT"

# Common fields carried by every entity except PaymentEvent (PRD §2.4)
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
# PaymentEvent carries only these two of the common four (PRD §2.4)
PAYMENT_EVENT_COMMON_FIELDS = ("id", "created_at")
