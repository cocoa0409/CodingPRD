"""Domain thresholds — numeric constants from the PRD's calculations and time rules."""

# Logical clock default boot instant (PRD §3.12).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Forecast (PRD §3.3): safety factor 1.25, fixed forward divisor 14 days.
SAFETY_FACTOR = 1.25
FORWARD_WINDOW_DAYS = 14

# Default note denomination when omitted on POST /atms (PRD §3.2).
DEFAULT_NOTE_DENOMINATION_CENTS = 2000

# Low-cash watermark: 2,000,000 cents = $20,000 (PRD §3.6).
LOW_WATERMARK_CENTS = 2_000_000

# Cash-count reconciliation default tolerance (PRD §3.6).
DEFAULT_TOLERANCE_CENTS = 500

# Interchange tiers selected marginally by monthly_seq (PRD §3.10).
TIER1_CENTS = 35      # monthly_seq 1..500
TIER2_CENTS = 42      # monthly_seq 501..2000
TIER3_CENTS = 50      # monthly_seq 2001+
TIER1_MAX_SEQ = 500
TIER2_MAX_SEQ = 2000

# Flat network fee per swept withdrawal (PRD §3.10).
NETWORK_FEE_PER_WD_CENTS = 8

# Commission basis-points denominator (PRD §3.11).
BPS_DENOMINATOR = 10_000

# Jurisdiction regulatory surcharge caps in cents (PRD §3.9).
REGULATORY_CAPS_CENTS = {
    "CA": 300,
    "NY": 500,
    "TX": 275,
    "FL": 300,
}

# ATM service-lockout buffer in minutes (PRD §3.5).
ATM_BUFFER_MIN = 30

# A vault baseline large enough that vault sufficiency never blocks a setup dispatch.
BIG_VAULT_PROVISIONED_CENTS = 100_000_000
