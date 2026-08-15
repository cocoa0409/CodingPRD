"""Domain thresholds — numeric constants from PRD calculation rules (§3.6, §3.7)."""

# Aging (PRD §3.6): three percent annual market escalation, compounded monthly.
ANNUAL_AGING_RATE = 0.03

# Geographic differential tables, in basis points (PRD §3.6).
METRO_TIER_BP = {
    "US-SF": 12800,
    "US-NYC": 12200,
    "US-SEA": 11200,
    "US-AUS": 10400,
    "US-REMOTE": 9500,
}
CUSTOM_GEO_INDEX_BP = {
    "US-SF": 13100,
    "US-NYC": 12400,
    "US-CHI": 10600,
    "US-REMOTE": 9200,
}
NEUTRAL_GEO_BP = 10000

# Industry premium table, in basis points (PRD §3.6).
INDUSTRY_PREMIUM_BP = {
    "HIGH_TECH": 10800,
    "FINANCIAL_SERVICES": 11200,
    "HEALTHCARE": 10300,
    "MANUFACTURING": 9800,
    "RETAIL": 9400,
    "ALL_INDUSTRIES": 10000,
}

# Weighted blend (PRD §3.6).
CONFIDENCE_FACTOR = {"HIGH": 1.00, "MEDIUM": 0.75, "LOW": 0.40}
CONSERVATIVE_LOW_CONFIDENCE_FACTOR = 0.20
MIN_FULL_SAMPLE = 30
CONSERVATIVE_MIN_SAMPLE = 10

# Compa-ratio position bands, in basis points (PRD §3.7).
BELOW_RANGE_BP = 8000
BELOW_TARGET_BP = 9500
AT_TARGET_UPPER_BP = 10500
ABOVE_TARGET_BP = 12000

# Single-adjustment cap: fifteen percent of current base (PRD §3.7).
MAX_SINGLE_ADJUSTMENT_BP = 1500

# Match approval statistical floor (PRD §3.5).
MIN_SAMPLE_SIZE_FOR_APPROVAL = 5

# Default logical-clock reading at server startup (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"
