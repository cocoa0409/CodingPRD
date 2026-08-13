"""Domain thresholds — numeric constants from PRD §3 calculation rules."""

THRESHOLDS = {
    # Trench geometry (PRD §3.4)
    "STANDARD_SEPARATION_IN": 12,
    "REDUCED_SEPARATION_IN": 6,
    "MIN_COVER_IN": 12,
    "CONCURRENT_SEPARATION_IN": 24,
    # Panel sizing (PRD §3.5)
    "PANEL_LOAD_FACTOR": 0.8,
    "PANEL_HEADROOM_FACTOR": 1.25,
    # Outage coordination (PRD §3.6)
    "MAX_CONCURRENT_OUTAGES": 2,
    "MAX_OUTAGE_HOURS": 8,
    "NOTIFICATION_LEAD_HOURS": 72,
    # Late fees (PRD §3.9)
    "LATE_FEE_GRACE_DAYS": 30,
    "STANDARD_LATE_RATE": 0.015,
    "ELEVATED_LATE_RATE": 0.02,
    "PRINCIPAL_TIER_THRESHOLD_CENTS": 10_000_000,
    "INVOICE_DUE_DAYS": 30,
    # Liquidated damages (PRD §3.7)
    "LD_RATE_CENTS_PER_DAY": 50_000,
    "LD_CAP_PCT": 0.10,
    # Restoration warranty (PRD §3.8)
    "WARRANTY_DAYS": 180,
    # Share basis (PRD §3.1)
    "FULL_SHARE_BP": 10_000,
    "VARIANCE_FLAG_PCT": 10,
}

# Logical clock startup value (PRD §2.5)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
