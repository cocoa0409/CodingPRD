"""Numeric constants, defaults and lookup tables taken from the PRD."""

# --------------------------------------------------------------------------- #
# Logical clock (PRD 2.6)
# --------------------------------------------------------------------------- #
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Pricing policy defaults (PRD 3.1)
# --------------------------------------------------------------------------- #
DEFAULT_SHIPPING_COUNTS_AS_ADVERTISED = False
DEFAULT_AUTO_COUPON_COUNTS_AS_ADVERTISED = True
DEFAULT_PROMO_CODE_COUNTS_AS_ADVERTISED = False
DEFAULT_MAX_DISCOUNT_ATTRIBUTION_PCT = 0.40
DEFAULT_NON_NEGOTIATION_ACK_REQUIRED = True
DEFAULT_CURE_WINDOW_DAYS = 10
DEFAULT_SUSPENSION_POINTS_THRESHOLD = 6
DEFAULT_TERMINATION_POINTS_THRESHOLD = 12
DEFAULT_SUSPENSION_COOLING_OFF_DAYS = 14

CURE_WINDOW_DAYS_MIN = 1
CURE_WINDOW_DAYS_MAX = 60
SUSPENSION_COOLING_OFF_DAYS_MIN = 0
SUSPENSION_COOLING_OFF_DAYS_MAX = 180
POLICY_CODE_MAX_LEN = 40

# --------------------------------------------------------------------------- #
# Product defaults (PRD 3.2)
# --------------------------------------------------------------------------- #
DEFAULT_CLEARANCE_DISCOUNT_PCT = 0.20
CLEARANCE_DISCOUNT_PCT_MAX = 0.60
DEFAULT_SERIALIZATION_ENABLED = True
SKU_MAX_LEN = 40
SERIAL_NUMBER_MAX_LEN = 40

# --------------------------------------------------------------------------- #
# Violation point arithmetic (PRD 3.5)
# --------------------------------------------------------------------------- #
# Severity tier from deviation_pct: (inclusive upper bound, base points).
SEVERITY_TIERS = [
    (0.0500, 1),
    (0.1500, 2),
    (0.3000, 4),
]
SEVERITY_TIER_TOP_POINTS = 6

CHANNEL_WEIGHTS = {
    "MARKETPLACE": 1.5,
    "RETAILER_SITE": 1.0,
    "OWN_WEBSITE": 1.0,
    "PHYSICAL_RETAIL": 0.5,
}

REPEAT_WEIGHT_BASE = 1.00
REPEAT_WEIGHT_STEP = 0.25
REPEAT_WEIGHT_MAX_PRIORS_COUNTED = 4
REPEAT_WEIGHT_CAP = 2.00
REPEAT_LOOKBACK_DAYS = 180

OBSERVATION_STALENESS_DAYS = 30

# --------------------------------------------------------------------------- #
# Pricing exception windows (PRD 3.6)
# --------------------------------------------------------------------------- #
EXCEPTION_WINDOW_MAX_DAYS = 180
RETROACTIVE_LOOKBACK_DAYS = 30
OVERRIDE_FLOOR_MIN_FRACTION_OF_STANDARD = 0.50

# --------------------------------------------------------------------------- #
# Enforcement ladder (PRD 3.7)
# --------------------------------------------------------------------------- #
RUNG_RANKS = {"WARNING": 1, "SUSPENSION": 2, "TERMINATION": 3}
RUNG_BY_RANK = {1: "WARNING", 2: "SUSPENSION", 3: "TERMINATION"}
MAX_RUNG_RANK = 3
SUSPENSION_MAX_DURATION_DAYS = 90
DISPUTE_ROUNDS_MAX = 2
DISPUTE_REJECT_CURE_EXTENSION_DAYS = 5

# --------------------------------------------------------------------------- #
# Chargebacks and diversion (PRD 3.9)
# --------------------------------------------------------------------------- #
CHARGEBACK_TIER_RATES = [
    (10.0, 2500),   # diversion_score < 10.0
    (25.0, 4000),   # 10.0 <= diversion_score < 25.0
]
CHARGEBACK_TOP_TIER_RATE = 6000  # diversion_score >= 25.0

SCORE_DELTA_PER_UNIT = 2.5

STANDING_PROBATION_THRESHOLD = 10.0
STANDING_SUSPENDED_THRESHOLD = 25.0

# --------------------------------------------------------------------------- #
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------- #
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------- #
# Evidence hashes: exactly 64 lowercase hexadecimal characters (PRD 3.5)
# --------------------------------------------------------------------------- #
EVIDENCE_HASH_1 = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b"
EVIDENCE_HASH_2 = "2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c"
EVIDENCE_HASH_3 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
EVIDENCE_HASH_4 = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
EVIDENCE_HASH_5 = "abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd"
EVIDENCE_HASHES = [
    EVIDENCE_HASH_1,
    EVIDENCE_HASH_2,
    EVIDENCE_HASH_3,
    EVIDENCE_HASH_4,
    EVIDENCE_HASH_5,
]


def evidence_hash(index):
    """Return a distinct valid 64-character lowercase hexadecimal hash."""
    if index < len(EVIDENCE_HASHES):
        return EVIDENCE_HASHES[index]
    return f"{index:064x}"
