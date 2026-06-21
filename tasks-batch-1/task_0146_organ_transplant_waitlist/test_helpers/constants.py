"""Domain thresholds — numeric constants from the PRD's scoring and timing rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# MELD-Na / PELD clinical scoring bounds (PRD §2.9, §3.3).
SCORING = {
    "MELD_FLOOR": 6,
    "MELD_CEIL": 40,
    "NA_LOW": 125.0,
    "NA_HIGH": 137.0,
    "DIALYSIS_CREAT": 4.0,
    "GROWTH_FAILURE_POINTS": 0.667,
    "PEDIATRIC_AGE_YEARS": 12,
    "DAYS_PER_YEAR": 365.25,
}

# Allocation priority point weights (PRD §3.5).
PRIORITY = {
    "MED_WEIGHT": 2.5,
    "WAIT_CAP_DAYS": 365,
    "WAIT_WEIGHT": 10,
    "HLA_WEIGHT": 1.5,
    "PEDIATRIC_BONUS": 8,
    "BROADER_SHARING_MULTIPLIER": 0.9,
}

# Size-match acceptance bands (PRD §3.5).
SIZE_BANDS = {
    "THORACIC_LO": 0.80,
    "THORACIC_HI": 1.20,
    "ABDOMINAL_LO": 0.70,
    "ABDOMINAL_HI": 1.50,
}

# Offer timing (PRD §3.7).
OFFER = {
    "RESPONSE_WINDOW_HOURS": 1,
}

# Time arithmetic (PRD §3.4, §3.9).
TIME = {
    "SECONDS_PER_DAY": 86400,
    "SECONDS_PER_HOUR": 3600,
}

# ABO donor → recipient compatibility map (PRD §3.5).
ABO_COMPAT_MAP = {
    "O": ["O", "A", "B", "AB"],
    "A": ["A", "AB"],
    "B": ["B", "AB"],
    "AB": ["AB"],
}
