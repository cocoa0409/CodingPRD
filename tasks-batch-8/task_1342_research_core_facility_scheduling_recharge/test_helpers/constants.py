"""Domain thresholds and canonical fixture values (PRD §2.4, §2.5, §3)."""

# --- PRD-pinned numeric constants ---
CERT_VALIDITY_MONTHS = 12               # PRD §3.3: certification validity
EARLY_CHECKIN_MINUTES = 15              # PRD §3.7: check-in opens 15 min before start
OPERATING_OVERHEAD_CENTS = 120000       # PRD §3.5/§3.13: flat overhead per instrument
MAX_RATE_INCREASE_PCT = 0.10            # PRD §3.5: year-over-year internal rate cap
RATE_DEVIATION_FLAG_PCT = 0.05          # PRD §3.13: deviation flag threshold
USAGE_LOG_LATE_CAP_HOURS = 24           # PRD §3.8: actual_end_at <= booking.end_at + 24h

# --- Logical clock ---
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"  # PRD §2.4 startup default

# --- Canonical instrument policy ("NMR-600") ---
CANONICAL_INSTRUMENT = {
    "name": "NMR-600",
    "model": "Bruker AV600",
    "location": "Lab 1",
    "requires_training": True,
    "booking_buffer_minutes": 30,
    "min_booking_minutes": 30,
    "max_booking_minutes": 480,
    "cancellation_free_notice_hours": 24,
    "late_cancel_penalty_pct": 0.5,
    "no_show_penalty_pct": 1.0,
}

# --- Canonical FY2026 rate line ---
CANONICAL_RATE_LINE = {
    "internal_rate_cents_per_hour": 12000,   # = 200 cents/min
    "external_rate_cents_per_hour": 18000,   # = 300 cents/min
    "billing_increment_minutes": 15,
    "min_charge_minutes": 30,
    "projected_billable_hours": 500,
    "break_even_waiver_reason": None,
}

# --- Canonical booking window (90 min => 18000 internal estimate) ---
CANONICAL_BOOKING_START = "2026-09-01T09:00:00Z"
CANONICAL_BOOKING_END = "2026-09-01T10:30:00Z"

CANONICAL_GRANT = {
    "grant_code": "NIH-1",
    "title": "Ion channels",
    "budget_total_cents": 100000,
    "start_date": "2026-01-01",
    "end_date": "2026-12-31",
}

# Derived canonical amounts (documented in PRD formulas)
CANONICAL_INTERNAL_RATE_PER_MIN = 200     # 12000 / 60
CANONICAL_EXTERNAL_RATE_PER_MIN = 300     # 18000 / 60
CANONICAL_90MIN_ESTIMATE = 18000          # 90 * 200
