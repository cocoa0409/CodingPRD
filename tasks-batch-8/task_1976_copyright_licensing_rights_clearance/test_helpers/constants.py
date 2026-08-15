"""Domain thresholds and desk constants from PRD §3."""

# Desk clock default before any set_current_utc call (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# DMCA counter window (PRD §3.7: "sets counter_notice_due_at ten days later").
DMCA_COUNTER_WINDOW_DAYS = 10

# Embargo buffer (PRD §3.2: "thirty days after that instant").
EMBARGO_BUFFER_DAYS = 30

# Reservation hold TTL (PRD §3.5: "seven hundred twenty hours — thirty days").
HOLD_TTL_HOURS = 720

# Renewal alert lead (PRD §3.4: "fires_at is thirty days before term_end_at").
RENEWAL_ALERT_LEAD_DAYS = 30

# Negotiation round cap (PRD §3.3: "at most five rounds").
MAX_NEGOTIATION_ROUNDS = 5

# Orphan certification (PRD §3.1: "at least three diligence logs ... span ... at least thirty days").
ORPHAN_MIN_CHANNELS = 3
ORPHAN_MIN_SPAN_DAYS = 30

# Fair use certification threshold (PRD §3.8: "a composite_score of at least 13").
FAIR_USE_CERTIFY_MIN = 13

# Bulk discount (PRD §3.3: "at least one hundred ... reduced by ten percent").
BULK_UNITS_MIN = 100
BULK_DISCOUNT = 0.10

# Media unit rates in cents (PRD §3.3).
MEDIA_UNIT_RATE_CENTS = {
    "BROADCAST_TV": 50000,
    "THEATRICAL": 80000,
    "STREAMING": 12000,
    "PRINT": 5000,
    "RADIO": 8000,
    "SOCIAL": 3000,
}

# Territory weights (PRD §3.3).
TERRITORY_WEIGHT = {
    "NA": 1.0,
    "EMEA": 1.4,
    "LATAM": 0.8,
    "APAC": 1.2,
    "WORLD": 3.0,
}

# Term tier multipliers (PRD §3.3: at most 90 days → 1.0; ≤365 → 1.25; longer → 1.6).
TERM_TIER_SHORT_MAX_DAYS = 90
TERM_TIER_MEDIUM_MAX_DAYS = 365
TERM_MULT_SHORT = 1.0
TERM_MULT_MEDIUM = 1.25
TERM_MULT_LONG = 1.6
