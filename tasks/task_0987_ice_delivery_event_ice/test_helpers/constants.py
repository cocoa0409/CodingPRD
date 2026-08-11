"""Domain thresholds and pinned constants from PRD §2.4, §2.9, §3.4-§3.9."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
# Common per-test starting instant used by fixtures.
CLOCK_2026_05_01_0900 = "2026-05-01T09:00:00Z"

# Dry-ice handling premium folded into line totals before rounding (PRD §3.4).
HANDLING_BPS = 700

# Per-unit weights in pounds (PRD §3.4).
WEIGHT_LBS = {
    ("CUBE", "BAG"): 7,
    ("CUBE", "PALLET"): 960,
    ("BLOCK", "BAG"): 25,
    ("BLOCK", "PALLET"): 300,
    ("DRY_ICE", "BAG"): 10,
    ("DRY_ICE", "PALLET"): 500,
}

# Bag-packaged lines consume one pallet space per twenty units, rounded up
# (PRD §3.4).
BAG_UNITS_PER_PALLET = 20

# Posture threshold: SURGE_CONSTRAINED when free <= ceil(capacity * 20%)
# (PRD §2.9).
SURGE_CONSTRAINED_THRESHOLD_PCT = 20

# Hold interval constants (PRD §3.5/§3.6).
STAGING_LEAD_HOURS = 4
GRACE_MINUTES = 60
VENTILATION_BUFFER_MINUTES = 30

# Route generation lead horizon in days (PRD §3.9 step 7).
ROUTE_GENERATION_LEAD_DAYS = 3

# Fixture price-book knobs shared by most tests (PRD §3.4 price stack).
BOOK_DEFAULTS = {
    "pallet_deposit_cents": 1500,
    "delivery_fee_cents": 4900,
    "free_delivery_threshold_cents": 20000,
    "surge_surcharge_bps": 1500,
}

# Common event dates/windows used by fixtures.
DEFAULT_EVENT_DATE = "2026-05-10"
DEFAULT_WINDOW_START = "10:00"
DEFAULT_WINDOW_END = "12:00"
