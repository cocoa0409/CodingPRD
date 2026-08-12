"""Domain thresholds and constants — from PRD §2.5, §3.4, §3.5, §3.6, §3.7."""

# Logical clock startup default (PRD §2.5: "that clock reads exactly 2026-05-01T00:00:00Z")
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Default billing/kitting period used across tests (YYYY-MM)
DEFAULT_PERIOD = "2026-05"
NEXT_PERIOD = "2026-06"
# First instant of the month after DEFAULT_PERIOD — the finalize gate opens here (PRD §3.7)
PERIOD_END_ISO = "2026-06-01T00:00:00Z"

# Postage pricing constants (PRD §3.5)
SLAB_GRAMS = 500
SERVICE_BASE = {"GROUND": 320, "EXPRESS": 745}
ZONE_RATE = {1: 25, 2: 40, 3: 55, 4: 75, 5: 95, 6: 120, 7: 150, 8: 185}
MIN_CHARGE = {"GROUND": 450, "EXPRESS": 990}
REMOTE_ZONE_MIN = 5
EXPRESS_REMOTE_SURCHARGE = 200

# Volume discount tiers in boxes (PRD §3.7 step three)
TIER5_BOXES = 200
TIER10_BOXES = 500

# Return approval window (PRD §3.6: thirty days after delivered_at)
RETURN_WINDOW_DAYS = 30

# Same-carrier pickup-window minimum gap (PRD §3.5)
WAVE_GAP_MINUTES = 30

# Standard test pickup windows (logical-clock friendly, May 2026)
WAVE_START_ISO = "2026-05-10T10:00:00Z"
WAVE_END_ISO = "2026-05-10T12:00:00Z"

TEST_DEFAULTS = {
    "PRICE_PER_BOX_CENTS": 1000,
    "SHIPPING_WEIGHT_GRAMS": 800,
    "UNIT_COST_CENTS": 10,
    "WALLET_SEED_CENTS": 100000,
    "ZONE": 2,
}
