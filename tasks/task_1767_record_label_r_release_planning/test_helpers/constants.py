"""Domain thresholds — numeric constants from PRD calculations."""

# Label config defaults (PRD §3.1)
DEFAULT_ADVANCE_CAP_CENTS = 5_000_000
DEFAULT_RESERVE_RATE_BPS = 1_000
DEFAULT_SIGN_THRESHOLD_SCORE = 40.0
DEFAULT_OPTION_WINDOW_DAYS = 90
DEFAULT_RELEASE_LEAD_DAYS = 21
DEFAULT_BEAT_PRE_RELEASE_DAYS = 42
DEFAULT_BEAT_POST_RELEASE_DAYS = 30
DEFAULT_CAMPAIGN_GAP_DAYS = 7

# Budget posture threshold (PRD §3.4): AT_RISK when (spent + committed) >= 85% of budget
AT_RISK_THRESHOLD_PCT_NUM = 85
AT_RISK_THRESHOLD_PCT_DEN = 100

# Royalty-rate hard ceiling (PRD §3.3)
MAX_BASE_RATE_BPS = 3_000

# Tier threshold defaults (PRD §3.1)
TIER_THRESHOLDS_DEFAULT = [
    {"units": 0, "delta_bps": 0},
    {"units": 500_000, "delta_bps": 200},
    {"units": 2_000_000, "delta_bps": 300},
]

# Channel deduction defaults (PRD §3.1)
CHANNEL_DEDUCTION_BPS_DEFAULT = {
    "STREAMING": 3_000,
    "DOWNLOAD": 1_500,
    "PHYSICAL": 2_500,
    "SYNC": 0,
}

# Tour category caps defaults (PRD §3.1 / §3.7)
TOUR_CATEGORY_CAPS_BPS_DEFAULT = {
    "TRAVEL": 5_000,
    "LODGING": 3_000,
    "PRODUCTION": 4_000,
    "MISC": 1_000,
}

# Genre multiplier defaults (PRD §3.1)
GENRE_MULTIPLIERS_DEFAULT = {
    "POP": 1.10,
    "HIPHOP": 1.05,
    "ROCK": 1.00,
    "ELECTRONIC": 0.95,
    "OTHER": 0.90,
}

# SYNC flat share (PRD §3.8): SYNC lines earn flat 50% of line net, ignore tiers
SYNC_FLAT_SHARE_NUM = 50
SYNC_FLAT_SHARE_DEN = 100

# Default logical clock at server startup (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
