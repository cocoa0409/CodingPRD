"""Domain constants (SCAFFOLD §1.3 / PRD §3)."""

# Forecast
SAFETY_FACTOR_NUM = 5     # 1.25 == 5/4, kept as integer ratio for exactness
SAFETY_FACTOR_DEN = 4
FORWARD_WINDOW_DAYS = 14
SECONDS_PER_DAY = 86400

# Interchange tiers (marginal by monthly_seq)
TIER1_CENTS = 35
TIER2_CENTS = 42
TIER3_CENTS = 50
TIER1_MAX_SEQ = 500
TIER2_MAX_SEQ = 2000

# Settlement
NETWORK_FEE_PER_WD_CENTS = 8

# Commission
BPS_DENOMINATOR = 10000

# Reconciliation
DEFAULT_TOLERANCE_CENTS = 500

# Cash watermark
LOW_WATERMARK_CENTS = 2000000  # $20,000

# Replenishment lockout buffer
ATM_BUFFER_SECONDS = 30 * 60  # 30 minutes each side

# Jurisdiction regulatory surcharge caps (cents)
REGULATORY_CAPS = {"CA": 300, "NY": 500, "TX": 275, "FL": 300}

# Enums
JURISDICTIONS = {"CA", "NY", "TX", "FL"}
COMMISSION_BASES = {"GREATER_OF", "PCT_ONLY", "FLAT_ONLY"}
CASSETTE_POSITIONS = {"C1", "C2", "C3", "C4"}
TXN_KINDS = {"WITHDRAWAL", "BALANCE_INQUIRY"}
FAULT_KINDS = {"CASH_JAM", "CARD_READER", "NETWORK", "DISPENSER"}
SEVERITIES = {"MINOR", "MAJOR"}
FORECAST_BASES = {"FORWARD", "CHRONOLOGICAL"}
