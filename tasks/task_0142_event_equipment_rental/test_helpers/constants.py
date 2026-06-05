"""Domain thresholds — numeric constants from the PRD's pricing rules (§3.3)."""

# Delivery-fee zone base fees in cents (PRD §3.3).
ZONE_BASE_CENTS = {
    "LOCAL": 5000,
    "EXTENDED": 9000,
    "REMOTE": 15000,
}

# Big-event surcharge added when total reserved units >= threshold (PRD §3.3).
SURCHARGE_CENTS = 4000
BIG_EVENT_UNIT_THRESHOLD = 100  # >= 100 units triggers surcharge (99 no, 100 yes)

# Free-delivery waiver: subtotal >= threshold waives the zone base (PRD §3.3).
FREE_DELIVERY_SUBTOTAL_CENTS = 200000  # 199999 no, 200000 yes

# Multi-day discount bounds (PRD §3.1).
MULTI_DAY_DISCOUNT_MIN = 0.0
MULTI_DAY_DISCOUNT_MAX = 0.90

# DeliveryRun reschedule is allowed only while attempt_count <= this (PRD §3.6).
MAX_RESCHEDULE_ATTEMPT_COUNT = 2

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
