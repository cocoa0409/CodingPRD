"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Sanctions screening thresholds (PRD 3.5).
SANCTIONS_CLEAR_THRESHOLD = 60      # score >= 60 -> HELD; < 60 -> auto CLEARED
SANCTIONS_ESCALATE_THRESHOLD = 85   # case escalation requires score >= 85

# KYC-tier per-transfer ceilings in minor units (PRD 3.4).
KYC_CEILING_TIER0_MINOR = 50000     # $500.00
KYC_CEILING_TIER1_MINOR = 300000    # $3,000.00
KYC_CEILING_TIER2_MINOR = 1500000   # $15,000.00

KYC_CEILINGS = {
    "TIER0": KYC_CEILING_TIER0_MINOR,
    "TIER1": KYC_CEILING_TIER1_MINOR,
    "TIER2": KYC_CEILING_TIER2_MINOR,
}

# Refund grace window and payout-attempt cap (PRD 3.6, 3.7).
REFUND_GRACE_SECONDS = 3600         # 1 hour fee-inclusive sender-cancel grace
MAX_PAYOUT_ATTEMPTS = 2             # delivery abandoned after this many FAILED attempts

# FX scaling (PRD 2.7).
SCALE_MICRO = 1000000

# Default weights for a sanctions list entry (PRD 3.1).
DEFAULT_WEIGHT_NAME_BPS = 7000
DEFAULT_WEIGHT_COUNTRY_BPS = 3000

# Corridor field defaults (PRD 3.1).
DEFAULT_ROLLING_WINDOW_HOURS = 24
DEFAULT_RATE_LOCK_TTL_SECONDS = 1800

# ─── Canonical corridor C1 (US->PH) config used across fixtures ──────────────
# fx_margin_bps=137, fee_flat_minor=199, fee_pct_bps=120,
# fee_tier_threshold_minor=100000, fee_pct_tier2_bps=70.
# With FxRate mid_rate_micro=56333333 the locked_rate_micro is 55561566.
#   P=50000  -> fee_minor=799,  recipient_amount_minor=2778078, total_pay=50799
#   P=100000 -> fee_minor=899,  recipient_amount_minor=5556156, total_pay=100899
CANONICAL_MID_RATE_MICRO = 56333333
CANONICAL_LOCKED_RATE_MICRO = 55561566

# Clock anchor used by fixtures (the FxRate is effective the day before).
CLOCK_ANCHOR_ISO = "2026-06-01T00:00:00Z"
FX_EFFECTIVE_ISO = "2026-05-31T00:00:00Z"
