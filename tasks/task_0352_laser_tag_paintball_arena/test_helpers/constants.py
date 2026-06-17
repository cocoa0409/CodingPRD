"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Add-on ammunition tiered pricing (PRD §3.5)
AMMO_TIER1_BALLS = 500       # first 500 balls
AMMO_TIER2_BALLS = 1500      # next 1500 balls (501st..2000th)
AMMO_RATE1_CENTS = 10        # $0.10 per ball, first 500
AMMO_RATE2_CENTS = 8         # $0.08 per ball, next 1500
AMMO_RATE3_CENTS = 6         # $0.06 per ball beyond 2000
CO2_CENTS = 700              # $7.00 per CO2 tank

# Booking invoice tax (PRD §3.8)
TAX_RATE = 0.0825            # 8.25% sales tax, per-line round-half-up

# Referee requirement threshold (PRD §3.6)
REFEREE_THRESHOLD = 12       # party_size >= 12 requires a referee
ADULT_AGE = 18               # age below this is a minor

# Reservation lead time (PRD §3.2)
MIN_LEAD_MINUTES = 60        # RESERVATION window_start must be >= now + 60min

# Default league scoring (PRD §3.9)
DEFAULT_WIN_POINTS = 3
DEFAULT_DRAW_POINTS = 1


THRESHOLDS = {
    "AMMO_TIER1_BALLS": AMMO_TIER1_BALLS,
    "AMMO_TIER2_BALLS": AMMO_TIER2_BALLS,
    "AMMO_RATE1_CENTS": AMMO_RATE1_CENTS,
    "AMMO_RATE2_CENTS": AMMO_RATE2_CENTS,
    "AMMO_RATE3_CENTS": AMMO_RATE3_CENTS,
    "CO2_CENTS": CO2_CENTS,
    "TAX_RATE": TAX_RATE,
    "REFEREE_THRESHOLD": REFEREE_THRESHOLD,
    "ADULT_AGE": ADULT_AGE,
    "MIN_LEAD_MINUTES": MIN_LEAD_MINUTES,
}

# A clock instant used as the canonical "now" anchor across fixtures.
CLOCK_BASE = "2026-06-15T09:00:00Z"
