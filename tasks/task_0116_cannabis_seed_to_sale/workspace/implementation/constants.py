"""Domain constants pinned from PRD/SCAFFOLD."""

# Flower-equivalent conversion factors (PRD §3.7).
FLOWER_EQUIV_FACTOR = {
    "FLOWER": "1.0",
    "CONCENTRATE": "5.0",
    "EDIBLE": "0.1",
}

# Medical customers enjoy 3x the daily limit (PRD §3.7, SCAFFOLD MEDICAL_LIMIT_MULTIPLIER).
MEDICAL_LIMIT_MULTIPLIER = 3

# Reconciliation tolerance: abs(variance) <= 0.5g is MATCH (PRD §3.8).
RECON_TOLERANCE_GRAMS = "0.5"

# Regulatory potency ceiling. thc_pct is constrained to [0,100]; the ceiling is
# the upper bound of the valid range, so any in-range potency is "at or below"
# the ceiling and the PASS/FAIL decision reduces to pesticide_pass (PRD §3.5).
POTENCY_CEILING_PCT = "100"

# Legal adult-use age in years at sale_date (PRD §3.7).
LEGAL_AGE_YEARS = 21

# Enum value sets.
LICENSE_TYPES = {"CULTIVATION", "MANUFACTURING", "RETAIL", "TESTING", "DISTRIBUTION"}
PRODUCT_CATEGORIES = {"FLOWER", "CONCENTRATE", "EDIBLE"}
WASTE_REASONS = {"MOLD", "PEST", "FAILED_TEST", "EXPIRED", "OTHER"}
WASTE_SOURCE_TYPES = {"PLANT_BATCH", "PACKAGE"}

ROLES = {
    "StateRegulator",
    "Cultivator",
    "QALabUser",
    "ComplianceManager",
    "DistributionAgent",
    "Budtender",
    "InventoryAuditor",
}
