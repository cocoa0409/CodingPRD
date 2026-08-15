"""Domain thresholds — numeric constants from PRD calculations."""

# Tariff schedule: HTS code -> ad valorem duty rate (PRD §3.3).
HTS_RATE_TABLE = {
    "0401.10": 0.05,
    "8542.31": 0.04,
    "9503.00": 0.12,
    "8708.29": 0.025,
}

# Merchandise processing fee constants (PRD §3.6).
MPF_AD_VALOREM_RATE = 0.003464
MPF_MIN_CENTS = 3000
MPF_MAX_CENTS = 60000

# Weekly entry window length in days (PRD §3.6).
ENTRY_WEEK_DAYS = 7

# Reconciliation audit threshold: flag when discrepancy_pct is strictly greater (PRD §3.7).
AUDIT_THRESHOLD_PCT = 0.5

# Logical clock startup default (PRD §2.5).
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "MPF_MIN_CENTS": MPF_MIN_CENTS,
    "MPF_MAX_CENTS": MPF_MAX_CENTS,
    "AUDIT_THRESHOLD_PCT": AUDIT_THRESHOLD_PCT,
    "ENTRY_WEEK_DAYS": ENTRY_WEEK_DAYS,
}
