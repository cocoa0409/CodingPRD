"""Domain thresholds and defaults — numeric constants from the Salon Spa Booking PRD.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Salon policy defaults (PRD §3.1).
SALON_DEFAULTS = {
    "no_show_fee_pct": 0.50,
    "no_show_suspend_threshold": 3,
    "tip_split_policy": "DIRECT",
    "timezone": "UTC",
}

# Stylist compensation defaults (PRD §3.1).
STYLIST_DEFAULTS = {
    "status": "ACTIVE",
    "commission_pct": 0.40,
    "booth_rent_per_appt_cents": 1500,
    "buffer_minutes": 10,
}

# Service defaults (PRD §3.1).
SERVICE_DEFAULTS = {
    "deposit_pct": 0.0,
    "requires_room": False,
}

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}

# A deterministic, valid future instant used across temporal fixtures.
# All temporal checks read the salon's simulated clock, never the host clock.
BASE_CLOCK_UTC = "2026-07-01T12:00:00Z"
