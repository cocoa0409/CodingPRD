"""Domain thresholds and time constants from the PRD calculations (§3)."""

# Time constants used by the pricing/overtime/rental calculations (PRD §3.4, §3.5, §3.6).
THRESHOLDS = {
    "HOURS_PER_RENTAL_DAY": 24,   # gear rental-day window (PRD §3.6)
    "MINUTES_PER_HOUR": 60,       # overtime conversion (PRD §3.4)
    "QUARTER_HOUR": 0.25,         # engineering quarter-hour rounding (PRD §3.5)
}

# Studio default commercial constants (PRD §3.1) — server-applied when omitted.
STUDIO_DEFAULTS = {
    "deposit_pct": 0.30,
    "overtime_multiplier": 1.5,
    "overtime_grace_minutes": 10,
    "cancellation_tier_hours": 48,
    "late_cancel_fee_pct": 0.50,
    "timezone": "UTC",
}

# Room default constants (PRD §3.1).
ROOM_DEFAULTS = {
    "block_hours": 8,
    "turnaround_minutes": 30,
}

# A fixed UTC instant used as the base clock for time-relative tests.
BASE_CLOCK = "2026-07-01T08:00:00Z"
