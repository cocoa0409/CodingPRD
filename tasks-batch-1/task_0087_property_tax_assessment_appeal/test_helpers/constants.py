"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3.4)."""

# Exemption deduction constants (PRD §3.4).
EXEMPTION_CONSTANTS = {
    "HOMESTEAD_FLAT": 7000,
    "SENIOR_FLAT": 5000,
    "SENIOR_PCT": 0.10,
    "VETERAN_FLAT": 4000,
    "DISABILITY_FACTOR": 0.50,
}

# Tax roll defaults (PRD §3.1).
DEFAULT_SENIOR_AGE_THRESHOLD = 65

# Board panel default (PRD §3.7).
DEFAULT_SETUP_BUFFER_MINUTES = 15

# Appeal negotiation round ceiling (PRD §3.6).
MAX_APPEAL_ROUNDS = 3

# Pagination defaults (PRD §2.3).
PAGINATION = {"limit_default": 10, "limit_min": 1, "limit_max": 100, "offset_default": 0}
