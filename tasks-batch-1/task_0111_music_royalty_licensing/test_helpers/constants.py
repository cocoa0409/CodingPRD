"""Domain thresholds — numeric constants from the PRD royalty/pricing rules (§3.7).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Performance pool royalty (§3.7)
PERFORMANCE = {
    "PRO_RATE": {"ASCAP": 12, "BMI": 11, "NONE": 0},   # cents per stream-minute
    "POOL_SHARE": 0.50,
    "DURATION_BASELINE_SECONDS": 180,                   # 3-minute baseline
    "DURATION_CAP": 3.0,
}

# Mechanical statutory royalty (§3.7)
MECHANICAL = {
    "BASE_PENNY_RATE": 12,            # cents per unit baseline (<= 300s)
    "PER_MINUTE_RATE": 2,            # cents per started minute, long-song tier
    "STREAM_FACTOR": 0.01,           # streams pay 1% of physical rate
    "LONG_SONG_THRESHOLD_SECONDS": 300,   # > 300s enters per-minute tier
}

# Sync quote fee (§3.7)
SYNC = {
    "MEDIA_MULT": {"FILM": 2.0, "TV": 1.5, "AD": 3.0, "GAME": 1.25},
    "TERR_WW_MULT": 2.5,
    "TERR_SMALL_DEAL_MULT": 1.2,
    "TERR_LARGE_DEAL_MULT": 1.0,
    "LARGE_DEAL_SUBTOTAL_CENTS": 500000,   # >= this subtotal -> large-deal tier
    "TERM_36_MULT": 1.6,             # term_months >= 36
    "TERM_12_MULT": 1.3,             # 12 <= term_months < 36
    "TERM_SHORT_MULT": 1.0,          # term_months < 12
}

# Rightsholder / payout defaults and bounds (§3.1)
DEFAULT_MINIMUM_PAYOUT_CENTS = 5000
DEFAULT_WITHHOLDING_PCT = 0.0
MAX_WITHHOLDING_PCT = 0.30

# RightsWindow SYNC cooldown buffer (§3.2)
SYNC_COOLDOWN_BUFFER_SECONDS = 86400

# Share / basis-point bounds (§3.1)
FULL_SPLIT_BPS = 10000
MIN_SPLIT_BPS = 1
MAX_SPLIT_BPS = 10000
