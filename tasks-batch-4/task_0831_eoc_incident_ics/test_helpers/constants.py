"""Domain thresholds — numeric constants from PRD calculations (§3.7, §3.8).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Declaration eligibility threshold (PRD §3.7): total_verified_damage >= this → ELIGIBLE.
DECLARATION_THRESHOLD = 5_000_000

# Enhanced federal-share tier (PRD §3.8): MAJOR_DISASTER and damage >= this → 90%.
ENHANCED_DAMAGE_THRESHOLD = 10_000_000

# Federal cost-share percentages (PRD §3.8).
BASE_SHARE_PCT = 0.75
ENHANCED_SHARE_PCT = 0.90

# Incident default cost ceiling (PRD §3.1).
DEFAULT_COST_CEILING = 100_000_000

THRESHOLDS = {
    "DECLARATION_THRESHOLD": DECLARATION_THRESHOLD,
    "ENHANCED_DAMAGE_THRESHOLD": ENHANCED_DAMAGE_THRESHOLD,
    "BASE_SHARE_PCT": BASE_SHARE_PCT,
    "ENHANCED_SHARE_PCT": ENHANCED_SHARE_PCT,
    "DEFAULT_COST_CEILING": DEFAULT_COST_CEILING,
}
