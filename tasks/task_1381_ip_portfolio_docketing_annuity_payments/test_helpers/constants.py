"""Domain thresholds — numeric constants from PRD rules (§3.4, §3.6, §3.9)."""

# Fixed pruning administration fee subtracted from gross savings (PRD §3.6).
PRUNE_ADMIN_FEE_CENTS = 15000

# Basis-point denominator for every basis-point rate (PRD §2.7).
BPS_DENOMINATOR = 10000

# Client risk-score weights per entry type (PRD §3.9).
RISK_WEIGHTS = {
    "STATUTORY": 10,
    "OFFICE_ACTION_RESPONSE": 4,
    "PARIS_PRIORITY": 8,
    "PCT_PHASE": 8,
    "ANNUITY": 6,
    "RECORDATION": 2,
}

# Client risk-score tiers (PRD §3.9).
RISK_TIER_CRITICAL_MIN = 50
RISK_TIER_ELEVATED_MIN = 20

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Common date anchors used by scenarios.
DEFAULT_GRANT_DATE = "2026-03-01"
DEFAULT_PRIORITY_DATE = "2026-01-15"
