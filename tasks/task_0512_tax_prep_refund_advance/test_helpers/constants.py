"""Domain thresholds — numeric constants from the PRD calculations (§2.7, §3.4, §3.7, §3.8)."""

# Preparation-fee computation (PRD §3.4)
PREP_FEE = {
    "BASE_1040_CENTS": 15000,
    "SCHEDULE_FEE": {"A": 4000, "B": 2500, "C": 9000, "D": 6000, "E": 7500, "EIC": 5000},
    "STATE_RETURN_CENTS": 6000,
    "BAND_MULT": {"SIMPLE": 1.00, "STANDARD": 1.20, "COMPLEX": 1.50},
    "DISCOUNT_PCT": 0.10,
    "DISCOUNT_CAP_CENTS": 2500,
}

# Refund-advance maximum-eligible computation (PRD §3.8)
ADVANCE = {
    "RISK_FRACTION": {"LOW": 0.75, "MEDIUM": 0.50, "HIGH": 0.00},
    "TIER_BREAKS_CENTS": [100000, 300000, 600000],
    "TIER_CAPS_CENTS": [0, 50000, 150000, 350000],
}

# Bank-product defaults (PRD §3.6, §3.7)
DEFAULT_BANK_PRODUCT_FEE_CENTS = 3995
DEFAULT_AUDIT_PROTECTION_FEE_CENTS = 5900

# Electronic-disbursement surcharge (PRD §3.7)
SURCHARGE_PCT = 0.029

# Capacity ceiling default (PRD §3.1)
DEFAULT_MAX_OPEN_RETURNS = 25

# Reject-loop lock threshold (PRD §3.5)
REJECT_LIMIT = 3

# Logical clock startup default (PRD §3.9)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
