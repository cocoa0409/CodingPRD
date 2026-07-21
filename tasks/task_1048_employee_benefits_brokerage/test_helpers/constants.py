"""Domain thresholds — numeric constants from PRD calculations."""

# Commission estimation (PRD §3.3)
COMMISSION_TIER1_CENTS = 6_000_000
COMMISSION_TIER2_CENTS = 12_000_000
BASE_MULT = 1.00
COMMISSION_TIER1_MULT = 1.05
COMMISSION_TIER2_MULT = 1.10
LINE_MULT = {"MEDICAL": 1.00, "DENTAL": 0.90, "VISION": 0.85, "LIFE": 0.95}

# ACA affordability (PRD §3.1)
AFFORDABILITY_PCT = 0.0912
FPL_ANNUAL_CENTS = 1_506_000

# Election tier factors (PRD §3.6)
TIER_FACTOR = {
    "EMPLOYEE_ONLY": 1.00,
    "EMPLOYEE_SPOUSE": 2.00,
    "EMPLOYEE_CHILD": 1.75,
    "FAMILY": 2.85,
}

# FTE / ALE (PRD §3.1)
ALE_THRESHOLD = 50

# Renewal floor (PRD §3.4)
RENEWAL_FLOOR_PCT = 0.50

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Logical clock startup default (PRD §2.9)
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"
