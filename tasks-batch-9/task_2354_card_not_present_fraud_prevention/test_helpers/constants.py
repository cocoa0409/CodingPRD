"""Domain thresholds, windows and worked expected values from the contract."""

from __future__ import annotations

from typing import Dict

from .types import (
    AddressClassification,
    AuthEventType,
    CustomerTier,
    Seniority,
)

# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------

#: Before any client touches it, the logical clock reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Good-customer standing
# ---------------------------------------------------------------------------

GOOD_CUSTOMER_MIN_APPROVED = 2
GOOD_CUSTOMER_MIN_NET_CENTS = 20000

# ---------------------------------------------------------------------------
# Velocity windows (seconds, inclusive at both ends)
# ---------------------------------------------------------------------------

VELOCITY_CUSTOMER_WINDOW_SECONDS = 3600
VELOCITY_DEVICE_CARD_WINDOW_SECONDS = 86400
VELOCITY_PROMO_ADDRESS_WINDOW_SECONDS = 2592000

VEL_CUSTOMER_1H_THRESHOLD = 3
VEL_DEVICE_CARD_24H_THRESHOLD = 3
PROMO_ADDRESS_ABUSE_THRESHOLD = 2
BEH_FAST_CHECKOUT_SECONDS = 45
BEH_BULK_CART_ITEMS = 10
DEV_MULTI_ACCOUNT_DISTINCT_CUSTOMERS = 3

# ---------------------------------------------------------------------------
# Score arithmetic caps
# ---------------------------------------------------------------------------

RULE_SCORE_CAP = 100
BLENDED_SCORE_CAP = 200.00
ATO_SCORE_CAP = 100.00
RESHIPPER_CONFIDENCE_CAP = 1.00
MODEL_POINTS_CAP = 100.00

RULE_DOMINANT_MODEL_DAMPEN = 0.35
RULE_DOMINANT_UPLIFT = 1.25

RULE_PACK_ACTIVATION_FREEZE_SECONDS = 3600

# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

SLA_SECONDS = 14400
AMOUNT_TERM_DIVISOR = 10000
AMOUNT_TERM_CAP = 20.00
GOOD_CUSTOMER_BOOST = 20.00
ESCALATION_BOOST = 15.00

TIER_PRIORITY_BOOST: Dict[str, float] = {
    CustomerTier.STANDARD: 0.00,
    CustomerTier.HIGH_VALUE: 10.00,
    CustomerTier.BUSINESS: 15.00,
}

SENIORITY_ORDER = (Seniority.JUNIOR, Seniority.SENIOR, Seniority.LEAD)

# ---------------------------------------------------------------------------
# Policy exceptions
# ---------------------------------------------------------------------------

TIER_EXCEPTION_CAP_CENTS: Dict[str, int] = {
    CustomerTier.STANDARD: 50000,
    CustomerTier.HIGH_VALUE: 500000,
    CustomerTier.BUSINESS: 2000000,
}

# ---------------------------------------------------------------------------
# Account-takeover scoring
# ---------------------------------------------------------------------------

ATO_EVENT_BASE: Dict[str, float] = {
    AuthEventType.LOGIN: 10.00,
    AuthEventType.PASSWORD_CHANGE: 25.00,
    AuthEventType.EMAIL_CHANGE: 30.00,
    AuthEventType.SHIP_ADDRESS_ADD: 20.00,
    AuthEventType.PAYMENT_INSTRUMENT_ADD: 35.00,
}

ATO_GEO_TERM = 25.00
ATO_FIRST_SEEN_DEVICE_TERM = 20.00
ATO_REPUTATION_TERM_BLOCKED = 40.00
ATO_REPUTATION_TERM_SUSPECT = 15.00
ATO_FAILURE_TERM_PER_FAILURE = 5.00
ATO_FAILURE_TERM_CAP = 15.00

ATO_STEPUP_FLOOR = 45.00
ATO_BLOCK_FLOOR = 75.00

CHALLENGE_TTL_SECONDS = 900
MAX_CHALLENGE_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Device and address ladders
# ---------------------------------------------------------------------------

DEVICE_BLOCKED_FRAUD_COUNT = 2
DEVICE_TRUSTED_MIN_APPROVED = 3
DEVICE_TRUSTED_MAX_DISTINCT = 2

RESHIPPER_PER_CUSTOMER = 0.20
RESHIPPER_MAX_COUNTED_CUSTOMERS = 3
RESHIPPER_PER_PROMO = 0.15
RESHIPPER_MAX_COUNTED_PROMOS = 2
RESHIPPER_FREIGHT_FORWARDER_TERM = 0.30
RESHIPPER_PO_BOX_TERM = 0.10

RESHIPPER_FLAT_TERM: Dict[str, float] = {
    AddressClassification.FREIGHT_FORWARDER: RESHIPPER_FREIGHT_FORWARDER_TERM,
    AddressClassification.PO_BOX: RESHIPPER_PO_BOX_TERM,
    AddressClassification.RESIDENTIAL: 0.00,
    AddressClassification.COMMERCIAL: 0.00,
}

# ---------------------------------------------------------------------------
# Training gate
# ---------------------------------------------------------------------------

REQUIRED_TRAINING_SEGMENTS = ("FRAUD_CNP", "FRAUD_ATO")
MIN_SAMPLES_PER_SEGMENT = 2

# ---------------------------------------------------------------------------
# Guarantee programme
# ---------------------------------------------------------------------------

GUARANTEE_COVERAGE_CAP_CENTS = 500000
GUARANTEE_FEE_BPS = 250

# ---------------------------------------------------------------------------
# The canonical scoring lattice used throughout the suite
# ---------------------------------------------------------------------------
# The reference rule pack is WEIGHTED with rule_weight 0.40, model_weight 0.60,
# review_floor_score 40.00 and decline_floor_score 60.00, holding a single
# BEH_FAST_CHECKOUT rule worth 20 points. An order with session_seconds 30 and
# cart_item_count 3 fires only that rule, so rule_score is 20. The reference
# risk model has calibration_intercept 0.05 and calibration_slope 1.20.
#
# Each entry maps a model_raw_probability to (model_points, weighted blended).

PACK_RULE_WEIGHT = 0.40
PACK_MODEL_WEIGHT = 0.60
PACK_REVIEW_FLOOR = 40.00
PACK_DECLINE_FLOOR = 60.00
PACK_RULE_POINTS = 20

MODEL_INTERCEPT = 0.05
MODEL_SLOPE = 1.20

FAST_CHECKOUT_SESSION_SECONDS = 30
NORMAL_CART_ITEM_COUNT = 3
SLOW_CHECKOUT_SESSION_SECONDS = 120

#: model_raw_probability that yields model_points 53.25 -> blended 39.95 (APPROVE).
PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR = 0.4021
#: model_raw_probability that yields model_points 53.34 -> blended 40.00 (REVIEW).
PROB_REVIEW_EXACTLY_AT_REVIEW_FLOOR = 0.4028
#: model_raw_probability that yields model_points 70.00 -> blended 50.00 (REVIEW).
PROB_REVIEW_MID_BAND = 0.5417
#: model_raw_probability that yields model_points 86.60 -> blended 59.96 (REVIEW).
PROB_REVIEW_JUST_UNDER_DECLINE_FLOOR = 0.6800
#: model_raw_probability that yields model_points 86.67 -> blended 60.00 (DECLINE).
PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR = 0.6806

MODEL_POINTS_AT_PROB = {
    PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR: 53.25,
    PROB_REVIEW_EXACTLY_AT_REVIEW_FLOOR: 53.34,
    PROB_REVIEW_MID_BAND: 70.00,
    PROB_REVIEW_JUST_UNDER_DECLINE_FLOOR: 86.60,
    PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR: 86.67,
}

WEIGHTED_BLENDED_AT_PROB = {
    PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR: 39.95,
    PROB_REVIEW_EXACTLY_AT_REVIEW_FLOOR: 40.00,
    PROB_REVIEW_MID_BAND: 50.00,
    PROB_REVIEW_JUST_UNDER_DECLINE_FLOOR: 59.96,
    PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR: 60.00,
}

#: Order amounts used repeatedly by the suite.
SMALL_ORDER_CENTS = 15000
STANDARD_ORDER_CENTS = 20000
LARGE_ORDER_CENTS = 75000

#: Tolerance for two-decimal score comparisons.
SCORE_TOLERANCE = 0.01
#: Tolerance for four-decimal rate comparisons.
RATE_TOLERANCE = 0.0001
