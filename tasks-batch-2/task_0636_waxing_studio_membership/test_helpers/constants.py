"""Domain thresholds — numeric constants from the PRD calculations and defaults."""

# Default clock at server startup (PRD 2.10).
DEFAULT_CLOCK_UTC = "2026-01-01T00:00:00Z"

# Threshold constants from the PRD business rules.
THRESHOLDS = {
    "CREDIT_PAR_CENTS": 100,          # cancel par-value conversion (PRD 3.3)
    "NO_SHOW_DEPOSIT_THRESHOLD": 2,   # deposit gating crosses at >= 2 active strikes (PRD 3.5)
    "STRIKE_TTL_DAYS": 90,            # strike expiry window (PRD 3.5 / 3.8)
    "NO_SHOW_SWEEP_MINUTES": 15,      # BOOKED -> NO_SHOW sweep at start+15m (PRD 3.6)
    "CHECKIN_EARLY_MINUTES": 30,      # check-in allowed at start-30m (PRD 3.6)
    "TIMELY_CANCEL_HOURS": 24,        # timely vs late cancel boundary (PRD 3.6)
    "RENEWAL_CYCLE_DAYS": 30,         # cycle length (PRD 3.3)
    "FREEZE_MIN_DAYS": 1,
    "FREEZE_MAX_DAYS": 90,
}

# Location-level defaults (PRD 3.1).
LOCATION_DEFAULTS = {
    "open_minute_of_day": 540,        # 09:00Z
    "close_minute_of_day": 1200,      # 20:00Z
    "deposit_required_cents": 1000,
    "no_show_fee_cents": 2500,
}

# ServiceType / Product defaults (PRD 3.1).
SERVICE_DEFAULTS = {
    "buffer_minutes": 5,
    "credit_cost": 1,
    "intro_eligible": False,
    "active": True,
}

PRODUCT_DEFAULTS = {
    "member_discount_pct": 0.10,
    "stock_qty": 100,
}

# Pagination bounds (PRD 2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "min_offset": 0,
}
