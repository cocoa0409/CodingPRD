"""Domain thresholds — numeric constants named by the PRD (§3)."""

# Cook-yield species coefficients (PRD §3.6)
FAT_COEFF = {
    "BOVINE": 0.16,
    "PORCINE": 0.14,
    "POULTRY": 0.10,
    "OVINE": 0.15,
    "MIXED": 0.12,
}
MEAL_COEFF = {
    "BOVINE": 0.24,
    "PORCINE": 0.22,
    "POULTRY": 0.30,
    "OVINE": 0.23,
    "MIXED": 0.25,
}
YIELD_TOLERANCE_PCT = 25.0

# Pickup fee / logistics (PRD §3.4)
TRANSPORT_COST_PER_MILE_CENTS = 150

# Order pricing (PRD §3.8)
GRADE_MULTIPLIER = {"PREMIUM": 1.05, "STANDARD": 1.00, "FEED_GRADE": 0.85}
FREIGHT_FLAT_CENTS = 12500

# Energy tiered tariff (PRD §3.6)
ENERGY_TIER1_LIMIT_HOURS = 500
ENERGY_TIER1_RATE_CENTS = 4200
ENERGY_TIER2_RATE_CENTS = 3800

# Odor score dynamics (PRD §3.2, §3.9)
SEVERITY_PENALTY = {"LOW": 50, "MEDIUM": 100, "HIGH": 150}
ODOR_RESTRICTED_THRESHOLD = 600
ODOR_RECOVERY_THRESHOLD = 700
ODOR_RECOVERY_PER_PERIOD = 50
ODOR_SCORE_CAP = 1000
ODOR_SCORE_FLOOR = 0

# Supplier discipline (PRD §3.3)
CONTAMINATION_STRIKE_LIMIT = 3

# Common test defaults
TEST_DEFAULTS = {
    "PLANT_NAME": "Plant A",
    "LOCATION": "Dallas TX",
    "COOKER_CAPACITY": 2,
    "STANDARD_COST_CENTS_PER_LB": 38,
    "EFFECTIVE_FROM": "2026-08-01",
    "EFFECTIVE_TO": "2026-12-31",
}
