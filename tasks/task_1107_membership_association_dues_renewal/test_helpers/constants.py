"""Domain thresholds — numeric constants from PRD calculations."""

# From dues_invoice_amount calculation
DAYS_IN_NON_LEAP = 365
DAYS_IN_LEAP = 366

# From chapter_share_amount calculation
BPS_DENOM = 10000

# Retry cap on failed payment attempts per DuesInvoice (§3.5)
MAX_FAILED_RETRY = 5

# member_risk_score component caps
RISK_FAILED_CAP = 40
RISK_EXPIRY_CAP = 30
RISK_USAGE_CAP = 30
RISK_FAILED_POINTS_PER_ATTEMPT = 20

# Default clock value at server start (§2.9)
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
