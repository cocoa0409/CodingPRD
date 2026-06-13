"""Domain thresholds — numeric constants from the PRD calculation narratives (§3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Materials cost / draw (PRD §3.5)
BASE_FRAME_ALLOWANCE_CENTS = 13000
FRAME_TIER_MULT = {
    "STANDARD": 1.00,
    "PREMIUM": 1.20,
    "DESIGNER": 1.50,
}

# Medical claim coinsurance (PRD §3.8)
MEDICAL_COINSURANCE_RATE = 0.80

# Remake window / surcharge (PRD §3.6)
REMAKE_WINDOW_DAYS = 90
MAX_REMAKES = 2
SURCHARGE_REMAKE_THRESHOLD = 2
REMAKE_SURCHARGE_CENTS = 2500

# Prescription expiry windows (PRD §3.3)
EYEGLASS_EXPIRY_MONTHS = 24
CONTACT_EXPIRY_MONTHS = 12

# Patient registration defaults (PRD §3.1)
DEFAULT_RECALL_INTERVAL_MONTHS = 12

# Benefit period length (PRD §3.4)
BENEFIT_PERIOD_MONTHS = 12

# A syntactically-valid UUID that is never minted by the server.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
