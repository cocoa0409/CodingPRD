"""Domain thresholds — numeric constants from PRD calculations."""

# Labor estimation
SQFT_PER_MIN = 50          # 50 cleanable sqft cleaned per crew-minute
CALLBACK_FACTOR = 0.40     # callback remediation estimated at 40% of a full routine pass

# Periodic add-on pricing
OVERAGE_MULTIPLIER = 1.5   # minutes beyond quote billed at 1.5x the straight rate

# Callback credit
MAJOR_BONUS_PCT = 0.05     # MAJOR severity adds 5 percentage points

# Defaults
DEFAULT_QUALITY_TARGET = 85
DEFAULT_SHIFT_CAPACITY_MIN = 480
DEFAULT_CALLBACK_CREDIT_PCT = 0.10
DEFAULT_QUALITY_HOLDBACK_PCT = 0.05

THRESHOLDS = {
    "SQFT_PER_MIN": SQFT_PER_MIN,
    "CALLBACK_FACTOR": CALLBACK_FACTOR,
    "OVERAGE_MULTIPLIER": OVERAGE_MULTIPLIER,
    "MAJOR_BONUS_PCT": MAJOR_BONUS_PCT,
    "DEFAULT_QUALITY_TARGET": DEFAULT_QUALITY_TARGET,
    "DEFAULT_SHIFT_CAPACITY_MIN": DEFAULT_SHIFT_CAPACITY_MIN,
    "DEFAULT_CALLBACK_CREDIT_PCT": DEFAULT_CALLBACK_CREDIT_PCT,
    "DEFAULT_QUALITY_HOLDBACK_PCT": DEFAULT_QUALITY_HOLDBACK_PCT,
}

# Canonical ClientContact owner id, threaded into Site.contact_user_id by fixtures.
DEFAULT_CONTACT_USER_ID = "cc-1"
