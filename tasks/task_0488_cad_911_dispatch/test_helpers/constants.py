"""Domain thresholds and constants from the PRD calculations."""

# Base priority by incident type (PRD §3.3).
BASE_PRIORITY = {
    "STRUCTURE_FIRE": 1,
    "ASSAULT_IN_PROGRESS": 1,
    "MEDICAL_EMERGENCY": 2,
    "TRAFFIC_COLLISION": 3,
    "ALARM": 4,
    "WELFARE_CHECK": 5,
}

# Required disciplines by incident type (PRD §3.3).
REQUIRED_DISCIPLINES = {
    "STRUCTURE_FIRE": ["FIRE", "EMS"],
    "MEDICAL_EMERGENCY": ["EMS"],
    "TRAFFIC_COLLISION": ["POLICE", "EMS"],
    "ASSAULT_IN_PROGRESS": ["POLICE"],
    "ALARM": ["POLICE"],
    "WELFARE_CHECK": ["POLICE"],
}

# Capability preference by incident type (PRD §3.4).
CAPABILITY_PREFERENCE = {
    "STRUCTURE_FIRE": ["ENGINE", "LADDER"],
    "MEDICAL_EMERGENCY": ["MEDIC_ALS", "MEDIC_BLS"],
    "TRAFFIC_COLLISION": ["PATROL", "MEDIC_BLS"],
    "ASSAULT_IN_PROGRESS": ["PATROL", "K9"],
    "ALARM": ["PATROL", "ENGINE"],
    "WELFARE_CHECK": ["PATROL"],
}

# The unknown-confidence degrade-safe priority clamp (PRD §3.3 step 4).
UNKNOWN_CONFIDENCE_CLAMP = 2

# Logical clock default at server startup (PRD §2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"
