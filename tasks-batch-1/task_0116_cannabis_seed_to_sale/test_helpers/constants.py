"""Domain thresholds — numeric constants from the PRD calculations and limits.

Generic NON_EXISTENT_UUID comes from the framework (re-exported via __init__).
"""

# Flower-equivalent conversion factors by product_category (PRD §3.7).
FLOWER_EQUIV_FACTOR = {
    "FLOWER": 1.0,
    "CONCENTRATE": 5.0,
    "EDIBLE": 0.1,
}

# Medical patients get a 3x daily limit multiplier (PRD §3.7).
MEDICAL_LIMIT_MULTIPLIER = 3

# Default per-customer daily flower-equivalent purchase cap for RETAIL (PRD §3.1).
DEFAULT_DAILY_PURCHASE_LIMIT_GRAMS = 28.5

# Reconciliation tolerance: |variance| <= 0.5g is a MATCH (inclusive) (PRD §3.8).
RECON_TOLERANCE_GRAMS = 0.5

# Legal adult-use age threshold at sale_date (PRD §3.7).
LEGAL_AGE = 21

# Decimal rounding precision for weights / flower-equivalent (PRD §2.9).
PRECISION_DP = 2

THRESHOLDS = {
    "MEDICAL_LIMIT_MULTIPLIER": MEDICAL_LIMIT_MULTIPLIER,
    "DEFAULT_DAILY_PURCHASE_LIMIT_GRAMS": DEFAULT_DAILY_PURCHASE_LIMIT_GRAMS,
    "RECON_TOLERANCE_GRAMS": RECON_TOLERANCE_GRAMS,
    "LEGAL_AGE": LEGAL_AGE,
}
