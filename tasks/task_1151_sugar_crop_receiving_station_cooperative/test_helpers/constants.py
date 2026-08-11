"""Domain thresholds and shared constants — numeric rules from PRD §3 calculations.

All values below appear verbatim in PRD.md §3.3–§3.10 (weight/factor/loss
constants), §2.9 (clock startup default), and the standard test window/slot
coordinates used by the composite fixtures.
"""

# --- Trash deduction (PRD §3.5) ---
LBS_PER_TON = 2000
FREE_TRASH_PCT = 3.00
HEAVY_TRASH_PCT = 10.00
HEAVY_MULTIPLIER = 1.5
REJECT_TRASH_PCT = 20.00

# --- Payment factor (PRD §3.5) ---
REF_SUGAR_PCT = 16.00
FACTOR_SLOPE = 0.04
PROV_CLAMP_MIN = 0.70
PROV_CLAMP_MAX = 1.30
LOW_SUGAR_PCT = 13.00
LOW_SUGAR_PENALTY = 0.05

# --- Deterioration (PRD §3.8) ---
DAILY_LOSS_PCT = 0.0008
LOSS_DECLARED_PCT = 5.00

# --- Pool accrual cap (PRD §3.7) ---
ACCRUAL_CAP_MULTIPLIER = 1.10

# --- Transport allowance bands (PRD §3.10): (band_max_miles, rate_cents_per_ton) ---
TRANSPORT_BANDS = [(15, 120), (40, 180), (80, 240), (None, 300)]

# --- Logical clock (PRD §2.9) ---
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# --- Standard campaign window used across fixtures ---
DEFAULT_WINDOW_START = "2026-09-15T00:00:00Z"
DEFAULT_WINDOW_END = "2026-11-20T00:00:00Z"
DEFAULT_BASE_PRICE_CENTS_PER_TON = 5500

# --- Standard delivery slots (half-open) and weigh clocks ---
SLOT_AM_START = "2026-10-01T08:00:00Z"
SLOT_AM_END = "2026-10-01T10:00:00Z"
SLOT_PM_START = "2026-10-01T10:00:00Z"
SLOT_PM_END = "2026-10-01T12:00:00Z"
WEIGH_CLOCK_AM = "2026-10-01T08:30:00Z"
WEIGH_CLOCK_PM = "2026-10-01T10:30:00Z"

# --- Laboratory personnel (opaque QUALITY_TECH identifiers, PRD §2.1) ---
QT_ALICE = "qt-alice"
QT_BOB = "qt-bob"
