"""Domain thresholds — numeric constants named by the PRD narratives."""

# Logical clock startup default (PRD §2.4: server starts at 2026-08-01T00:00:00Z).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Animal-unit factor inputs (PRD §3.3).
REF_WEIGHT_LBS = 1000
WEIGHT_AU_COEF = 0.30
BASE_AU = {
    "MATURE_COW": 1.00,
    "REPLACEMENT_HEIFER": 0.70,
    "GROWING": 0.75,
}

# One AUM is one animal unit grazing for a 30-day month (PRD §2.6).
DAYS_PER_AUM_MONTH = 30

# Posture scaling of effective capacity (PRD §2.9).
POSTURE_FACTOR = {
    "NORMAL": 1.00,
    "WATCH": 0.85,
    "ALERT": 0.70,
    "CRITICAL": 0.50,
}

# Posture thresholds on ranch_production_pct (PRD §3.8).
THRESHOLD_WATCH = 90
THRESHOLD_ALERT = 75
THRESHOLD_CRITICAL = 55
SEASON_MONTHS = 5

# Bull battery sizing (PRD §3.4): one bull per 25 exposed females, rounded up.
COWS_PER_BULL = 25

# Minimum bull turnaround gap in days (PRD §3.4).
MIN_BULL_TURNAROUND_DAYS = 7

# Preconditioning (PRD §3.6).
PRECON_MIN_WEAN_DAYS = 45
VACCINE_MIN_SPACING_DAYS = 14

# Dam-age adjustment pounds for the adjusted 205-day weight (PRD §3.6).
DAM_ADJ_LBS = {
    2: 54,
    3: 20,
    "4_TO_10": 0,
    "11_PLUS": 20,
}

# Sale settlement premium per cwt by preconditioning claim (PRD §3.7).
PREMIUM_CENTS_PER_CWT = {
    "NONE": 0,
    "ENROLLED": 250,
    "CERTIFIED": 600,
}
MIN_PRICE_CENTS_PER_CWT = 100

# Defaults (PRD §3.1 / §3.2).
DEFAULT_DESTOCK_GRACE_DAYS = 30
DEFAULT_MIN_REST_DAYS = 45

# Common default terms for a grazing lease payload.
DEFAULT_LEASE_TERMS = {
    "rate_per_aum_cents": 2500,
    "minimum_commit_aum": 100,
    "overage_tier1_cap_aum": 50,
    "overage_tier1_rate_cents": 3000,
    "overage_tier2_rate_cents": 3750,
}
