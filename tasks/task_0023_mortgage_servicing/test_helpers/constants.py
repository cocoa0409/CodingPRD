"""Domain thresholds and numeric constants drawn from PRD prose.

Each constant is named in the PRD (§2.4, §2.8, §2.9, §3.2-§3.8, §5).
"""

# Grace and delinquency boundaries (PRD §3.3, §3.5).
GRACE_DAYS = 15
FORECLOSURE_THRESHOLD_DAYS = 120

# Sale and mediation notice windows (PRD §3.5).
SALE_NOTICE_DAYS = 30
MEDIATION_NOTICE_DAYS = 14

# Forbearance window cap (PRD §3.4).
MAX_FORBEARANCE_MONTHS = 12
MAX_FORBEARANCE_DAYS = 360

# Escrow cushion cap per RESPA (PRD §3.6).
MAX_CUSHION_MONTHS = 2

# PMI eligibility thresholds in basis points (PRD §3.8).
LTV_BORROWER_REQUEST_BPS = 8000   # 80.00%
LTV_AUTO_TERMINATION_BPS = 7800   # 78.00%

# Clean-payment-history window (PRD §3.8).
CLEAN_HISTORY_WINDOW_DAYS = 365
CLEAN_HISTORY_MAX_DPD = 30

# Foreclosure cure-amount flat surcharge (PRD §3.5: $2,500 = 250000 cents).
FORECLOSURE_FEE_FLAT_CENTS = 250000

# Late fee percentage of scheduled P&I in basis points (PRD §3.2: "five percent").
LATE_FEE_PCT_BPS = 500

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
