"""Domain thresholds — numeric constants from PRD §3 pricing / §2.4 clock."""

# Initial logical-clock instant the server boots with (PRD §2.4).
INITIAL_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Per-leg-kind base cents (PRD §3.3).
LEG_BASE_CENTS = {
    "MEET_ARRIVAL": 6000,
    "DEPARTURE_ESCORT": 7500,
    "CONNECTION_TRANSFER": 9500,
}

# Flat fees (PRD §3.3).
COMPANION_FEE_CENTS = 1500
WCHR_FEE_CENTS = 800
WCHC_FEE_CENTS = 1800
UMMR_FEE_CENTS = 2500
SENIOR_FEE_CENTS = 900
TSA_ESCORT_FEE_CENTS = 1200

# Tier multipliers in basis points (PRD §3.3).
TIER_MULT_BP = {
    "STANDARD": 10000,
    "PRIORITY": 12500,
    "CONCIERGE": 15000,
}

# Posture multipliers in basis points (PRD §3.3).
POSTURE_MULT_BP = {
    "NORMAL": 10000,
    "DEGRADED": 12500,
    # LOCKDOWN n/a — request is cancelled
}

# Delay-surcharge inputs for the final leg charge (PRD §3.6).
GRACE_MINUTES = 20
DELAY_PER_MIN_CENTS = 75

# Wheelchair maintenance threshold (PRD §3.4).
MAINT_INTERVAL = 50

# Per-leg-kind estimated transfer minutes (PRD §3.4 agent_shift_overlap).
ESTIMATED_TRANSFER_MINUTES = {
    "MEET_ARRIVAL": 45,
    "DEPARTURE_ESCORT": 60,
    "CONNECTION_TRANSFER": 75,
}

# Airport creation lower bound (PRD §3.1).
MEET_BUFFER_MIN_MINUTES = 15

# No-show threshold (PRD §3.10).
NO_SHOW_THRESHOLD_MINUTES = 30

# Stale-request epoch window (PRD §3.7).
STALE_REQUEST_EPOCHS = 2
