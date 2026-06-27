"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3.4, §3.6, §3.7, §3.8)."""

# Good-faith-exam validity window (§3.4): exam fresh only while
# exam_clock_utc + 365 days is strictly after the current clock.
GOOD_FAITH_EXAM_VALIDITY_DAYS = 365

# Touch-up round cap (§3.7): a touch-up may open only while touchup_rounds < 2.
MAX_TOUCHUP_ROUNDS = 2

# Loyalty point redemption value (§2.6, §3.6): one point == one cent.
POINT_VALUE_CENTS = 1

# Provider complication rate scale (§3.8): rates expressed in basis points.
RATE_SCALE_BPS = 10000

# Logical server clock default at startup (§2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

THRESHOLDS = {
    "GOOD_FAITH_EXAM_VALIDITY_DAYS": GOOD_FAITH_EXAM_VALIDITY_DAYS,
    "MAX_TOUCHUP_ROUNDS": MAX_TOUCHUP_ROUNDS,
    "POINT_VALUE_CENTS": POINT_VALUE_CENTS,
    "RATE_SCALE_BPS": RATE_SCALE_BPS,
}
