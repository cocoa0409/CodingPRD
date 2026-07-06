"""Domain thresholds — numeric constants from the PRD's calculations."""

# --- Complaint priority scoring (PRD 3.1) ---
SEVERITY_BASE = {
    "BITE": 50,
    "DANGEROUS_DOG": 40,
    "CRUELTY": 35,
    "STRAY": 15,
    "NOISE": 5,
    "OTHER": 10,
}
ANIMAL_MULT = {
    "WILDLIFE": 1.5,
    "DOG": 1.2,
    "LIVESTOCK": 1.1,
    "CAT": 1.0,
    "OTHER": 1.0,
}
REPEAT_STEP = 5
REPEAT_CAP = 20
VULNERABLE_BONUS = 15
P1_THRESHOLD = 60
P2_THRESHOLD = 30

# --- Citation fine (PRD 3.7) ---
VIOLATION_FINE = {
    "UNLICENSED": 50,
    "LEASH": 75,
    "DANGEROUS": 250,
    "BITE": 300,
    "CRUELTY": 500,
}
REPEAT_STEP_PCT = 0.5
CITATION_REPEAT_CAP = 3

# --- Case risk scoring (PRD 3.4) ---
TYPE_WEIGHT = {
    "BITE": 40,
    "DANGEROUS_DOG": 35,
    "CRUELTY": 30,
    "STRAY": 10,
}
SEV_FACTOR = 0.5
SUBSTANTIATION_BONUS = 20
RISK_MIN = 0
RISK_MAX = 100

# --- Impound boarding fee (PRD 3.6) ---
DAILY_RATE = 12.50
INTAKE_FEE = 15.00
UNLICENSED_SURCHARGE = 22.75
TAX_RATE = 0.075
SECONDS_PER_DAY = 86400

# --- Quarantine observation window (PRD 3.5) ---
BITE_DAYS = 10
DANGEROUS_DOG_DAYS = 14

# --- Officer / dispatch defaults (PRD 3.2) ---
DEFAULT_MAX_DAILY_DISPATCHES = 8

# --- Logical clock (PRD 2.5) ---
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# --- Pagination defaults (PRD 2.3) ---
DEFAULT_PAGE_LIMIT = 10
DEFAULT_PAGE_OFFSET = 0
