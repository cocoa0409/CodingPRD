"""Domain thresholds — numeric constants named by PRD §3 rules."""

# PRD §2.5: the logical clock starts at exactly this instant before any
# operator sets it; the server never falls back to wall-clock time.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# PRD §3.3 / §3.8: deduction percentage by inspected (or declared) condition.
DEDUCTION_PCT = {
    "NEW": 0.0,
    "LIGHT_USE": 0.10,
    "DAMAGED": 0.50,
    "DEFECTIVE": 0.0,
    "WRONG_ITEM": 1.00,
}

# PRD §3.2: volume-discount tiers evaluated on the gross charge.
DISCOUNT_TIER1_GROSS_CENTS = 200000
DISCOUNT_TIER1_PCT = 0.05
DISCOUNT_TIER2_GROSS_CENTS = 500000
DISCOUNT_TIER2_PCT = 0.10

# PRD §3.3: overage hard cap — projected load strictly greater than twice the
# plan's included_returns is rejected; exactly equal is allowed.
OVERAGE_HARD_CAP_MULTIPLIER = 2

# PRD §3.5: slot hold window is exactly 48 hours, half-open
# [hold_start, hold_until).
SLOT_HOLD_HOURS = 48

# PRD §3.4: label lifetime is exactly ten days from issue; at exactly
# expires_at the label is expired.
LABEL_TTL_DAYS = 10

# PRD §3.7: tote manifest capacity bounds; landing exactly on either bound is
# allowed.
TOTE_MAX_UNITS = 40
TOTE_MAX_WEIGHT_GRAMS = 30000

# PRD §3.3: shopper restricted when fraud strikes reach two; exactly one
# strike leaves the shopper ACTIVE.
FRAUD_STRIKE_RESTRICT_THRESHOLD = 2

# PRD §3.5: locker dimension ceiling by size class (cm, longest side, inclusive).
SLOT_SIZE_CEILING_CM = {"S": 30, "M": 60, "L": 100, "XL": 150}

# PRD §3.3 / §3.5: items whose longest side exceeds 150 cm are oversize and
# forbidden in locker flows.
OVERSIZE_DIM_CM = 150

# PRD §3.9: a case may be appealed while appeal_count < 2.
APPEAL_LIMIT = 2

# PRD §3.6: a FAILED appointment may be rescheduled while attempt_count < 3.
PICKUP_MAX_ATTEMPTS = 3

# A UUID that never refers to a persisted resource (used in 404 tests).
NON_EXISTENT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
