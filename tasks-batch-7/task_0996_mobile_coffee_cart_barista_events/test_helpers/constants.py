"""Domain thresholds and numeric constants from PRD calculations (§2.5, §3.2–§3.8).

All monetary values are integer cents (PRD §2.6).
"""

# ─── Logical clock ────────────────────────────────────────────────────────
# Server startup default; tests pin the clock explicitly before anything else.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# ─── Pricing / quoting (PRD §3.3) ─────────────────────────────────────────
CUPS_PER_GUEST = 1.5            # cup estimate factor for PER_CUP_METERED
METERED_MAX_KM = 25             # distance_km <= 25 -> METERED travel variant
DEPOSIT_PCT = 0.30              # raw deposit = 30% of quoted_total_cents
DEPOSIT_MIN_CENTS = 1000        # deposit_due_cents lower clamp
DEPOSIT_MAX_CENTS = 50000       # deposit_due_cents upper clamp

# ─── Cancellation refund policy (PRD §3.8) ────────────────────────────────
LONG_NOTICE_THRESHOLD_HOURS = 168   # 7 full days
SHORT_NOTICE_FACTOR = 0.5           # haircut applied below the threshold

# ─── Scheduling (PRD §3.2, §3.5, §3.8) ────────────────────────────────────
MIN_BOOKING_LEAD_HOURS = 24     # event_start must be >= 24h ahead of the clock
TRAVEL_BUFFER_MINUTES = 90      # cart schedule buffer on each side of an event
AMEND_WINDOW_HOURS = 48         # amend requires event > 48h ahead

# ─── Standard catalog fixtures (shared by many scenarios) ─────────────────
STANDARD = {
    "FLAT_PRICE_CENTS": 60000,          # PKG-FLAT
    "PER_CUP_PRICE_CENTS": 450,         # PKG-CUP
    "PER_CUP_MINIMUM_CENTS": 25000,     # PKG-CUP
    "ZONE1_PER_KM_RATE_CENTS": 200,     # ZONE-1
    "ZONE1_BANDED_FEE_CENTS": 5000,     # ZONE-1
    "WEEKLY_HOUR_CAP": 40,
    "HOURLY_RATE_CENTS": 3000,
}
