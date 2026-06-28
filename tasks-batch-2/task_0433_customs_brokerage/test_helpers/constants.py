"""Domain thresholds — numeric constants from the PRD charge calculations."""

# Duty rates in basis points, selected by HTS chapter (first two digits).
DUTY_RATE_BPS = {
    "APPAREL": 1650,      # chapters 61, 62
    "MACHINERY": 250,     # chapters 84, 85
    "GENERAL": 500,       # any other chapter
}

# Merchandise processing fee: ad valorem with statutory floor and ceiling.
MPF_RATE_BPS = 35
MPF_MIN_CENTS = 3215
MPF_MAX_CENTS = 62333

# Harbor maintenance fee (waived for FTZ_06 entries; no cap).
HMF_RATE_BPS = 13

# Excise proxy tax applied when any line is FDA-flagged.
EXCISE_TAX_BPS = 200

# General duty rate used for PSC/PROTEST adjustments.
DUTY_RATE_BPS_GENERAL = 500

# Advance-filing cutoff: ISF must be on file >= 24h before vessel_eta.
ISF_CUTOFF_HOURS = 24

# Countries eligible for verified USMCA zero-duty at liquidation.
FTA_ELIGIBLE_ORIGINS = ["MX", "CA"]

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Server logical-clock startup default (PRD §3.11).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that resolves to no resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
