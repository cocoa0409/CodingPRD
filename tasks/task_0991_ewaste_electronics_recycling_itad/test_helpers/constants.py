"""Domain thresholds and money constants from the PRD (§3.1, §3.2, §3.8)."""

# Logical clock startup default (PRD §2.9).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Quote valuation catalog (PRD §3.8): base value per category, cents.
BASE_VALUE_CENTS = {
    "LAPTOP": 40000,
    "DESKTOP": 25000,
    "SERVER": 120000,
    "PHONE": 15000,
    "TABLET": 18000,
    "MONITOR": 8000,
    "BATTERY": 0,
    "OTHER": 5000,
}

# Grade multipliers (PRD §3.8).
GRADE_MULT = {"A": 1.0, "B": 0.7, "C": 0.4, "D": 0.1}

# Sale commission per account tier (PRD §3.6).
COMMISSION_RATE = {"STANDARD": 0.15, "VOLUME": 0.15, "ENTERPRISE": 0.10}

# Recycling fee category bases, cents (PRD §3.8).
CATEGORY_BASE_FEE_CENTS = {
    "LAPTOP": 800,
    "DESKTOP": 1000,
    "SERVER": 2500,
    "PHONE": 300,
    "TABLET": 400,
    "MONITOR": 1200,
    "BATTERY": 1500,
    "OTHER": 900,
}

# Weight-tiered per-kg rates, cents/kg (PRD §3.8).
WEIGHT_PER_KG_RATE = {"LIGHT": 120, "MID": 90, "HEAVY": 60}
LIGHT_MAX_KG = 5.0    # w < 5.0 -> LIGHT
MID_MAX_KG = 20.0     # 5.0 <= w <= 20.0 -> MID; w > 20.0 -> HEAVY

HAZMAT_SURCHARGE_CENTS = 2000

# Sanitization fee per method, cents (PRD §3.8).
SANITIZATION_FEE_CENTS = {
    "CRYPTO_ERASE": 500,
    "NIST_CLEAR": 700,
    "NIST_PURGE": 1000,
    "PHYSICAL_DESTROY": 1500,
}
QUOTE_DEFAULT_SANITIZATION_METHOD = "NIST_CLEAR"

PICKUP_FEE_CENTS = 15000

# Volume rebate (PRD §3.8), keyed on the pre-rebate net.
REBATE_RATE = {"GOLD": 0.05, "SILVER": 0.02, "NONE": 0.0}
GOLD_FLOOR_CENTS = 500000
SILVER_FLOOR_CENTS = 100000

# Account tier thresholds, kg, inclusive (PRD §3.1).
VOLUME_THRESHOLD_KG = 1000
ENTERPRISE_THRESHOLD_KG = 5000

# Recycler risk score constants (PRD §3.2).
CERT_HORIZON_DAYS = 365
VOLUME_SATURATION_KG = 10000
VIOLATION_SATURATION = 10
