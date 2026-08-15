"""Domain thresholds and shared fixture literals (PRD §3 calculations).

All monetary values are integer cents (PRD §2.9).
"""

# --- Paint material estimate (PRD §3.4) ---
COVERAGE_SQFT_PER_GAL = 350
ACCENT_COVERAGE_SQFT_PER_GAL = 500
SCUFF_MATERIAL_FACTOR = 0.85
TIER1_MAX_GAL = 20
TIER1_RATE_CENTS = 18500
TIER2_MAX_GAL = 60
TIER2_RATE_CENTS = 17250
TIER3_RATE_CENTS = 16000

# --- Weight & balance (PRD §3.9) ---
FILM_LB_PER_SQFT_COAT_EST = 0.006      # PROVISIONAL variant
FILM_LB_PER_SQFT_COAT_ACTUAL = 0.0058  # FINAL variant

# --- Booth utilization (PRD §3.2) ---
OVERRUN_PREMIUM_MULT = 1.25

# --- Invoice milestones and handling (PRD §3.12) ---
DEPOSIT_PCT = 0.10
PROGRESS_PCT = 0.40
DISCOVERY_HANDLING_PCT = 0.10

# --- Burn certification (PRD §3.8) ---
MAX_RETESTS = 3

# --- Major-defect auto-discovery threshold (PRD §3.11) ---
MAJOR_DEFECT_THRESHOLD = 2

# --- Logical clock startup default (PRD §2.4) ---
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Shared fixture literals used across the suite ---
FIXTURE = {
    "CUSTOMER_NAME": "Apex Aviation LLC",
    "CUSTOMER_EMAIL": "ops@apex.example",
    "TAIL_NUMBER": "N1869A",
    "AIRCRAFT_MODEL": "G650",
    "MAX_DELTA_LBS": 50.0,
    "BASE_PRICE_CENTS": 12345673,
    "DAILY_PENALTY_RATE_CENTS": 150000,
    "PENALTY_CAP_PCT": 0.10,
    "CONTRACTUAL_DELIVERY_DATE": "2026-09-01",
    "DRAWING_REF": "DWG-1869-A",
    "PAINTED_AREA_SQFT": 2400,
    "COAT_COUNT": 2,
    "STRIPE_PCT": 0.10,
    "BAY_NAME": "BAY-1",
    "BAY_DAILY_RATE_CENTS": 85000,
    "BOOTH_NAME": "BOOTH-1",
    "BOOTH_HOURLY_RATE_CENTS": 25000,
    "BOOTH_CURE_BUFFER_HOURS": 6,
    # Slot covering the startup clock instant so it can be activated at once.
    "SLOT_START": "2026-08-01T00:00:00Z",
    "SLOT_END": "2026-08-22T00:00:00Z",
    # An 8-hour spray window.
    "BOOTH_WINDOW_START": "2026-08-10T08:00:00Z",
    "BOOTH_WINDOW_END": "2026-08-10T16:00:00Z",
    "SCHEDULED_HOURS": 8,
    "LAB_NAME": "AeroBurn Labs",
    "TECH_USER_ID": "tech-1",
    "QI_USER_ID": "qi-1",
}
