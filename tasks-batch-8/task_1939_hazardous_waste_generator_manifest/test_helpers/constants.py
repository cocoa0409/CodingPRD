"""Domain thresholds — numeric constants from PRD calculation rules."""

# Generator category thresholds (PRD §2.6)
SQG_EXCLUSIVE_LOWER_KG = 100.0      # strictly above -> SQG
LQG_INCLUSIVE_THRESHOLD_KG = 1000.0  # at least -> LQG

# Satellite accumulation (PRD §3.3)
SATELLITE_LIMIT_GAL = 55.0          # strictly over -> SATELLITE_LIMIT_EXCEEDED
MOVE_GRACE_DAYS = 3                 # move_deadline_at = satellite_exceeded_at + 3 days

# Accumulation allowance (PRD §3.3, category-at-start snapshot)
LQG_DEADLINE_DAYS = 90
OTHER_DEADLINE_DAYS = 180           # SQG or VSQG

# Inspection cadence (PRD §3.4)
INSPECTION_INTERVAL_DAYS = 7        # strictly more than 7 days past baseline -> overdue

# Manifest return window (PRD §3.7/§3.8)
RETURN_WINDOW_DAYS = 45

# Money (PRD §2.10, §3.9)
RATE_CENTS_PER_KG = 10.5
LQG_BASE_CENTS = 250000
SQG_BASE_CENTS = 100000
VSQG_BASE_CENTS = 25000
LATE_PER_DAY_CENTS = 5000
LATE_CAP_CENTS = 150000

CATEGORY_BASE_CENTS = {"LQG": LQG_BASE_CENTS, "SQG": SQG_BASE_CENTS, "VSQG": VSQG_BASE_CENTS}

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_MONTH_KEY = "2026-08"

# Convenience audit windows used by fixtures
AUDIT_WINDOW_DEFAULT = ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
AUDIT_WINDOW_WIDE = ("2025-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
