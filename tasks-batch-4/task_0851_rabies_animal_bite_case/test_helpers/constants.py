"""Domain thresholds and constants from the PRD calculations."""

# PEP dose projection (PRD Section 3.6).
DOSE_COST_CENTS = 30000
RIG_COST_CENTS = 120000
STANDARD_DOSES = 4

# Quarantine (PRD Section 3.3 / 3.4).
QUARANTINE_DAYS = 10

# Citation fine schedule (PRD Section 3.7).
SURCHARGE_PCT = 0.085
BASE_FINES = {
    "QUARANTINE_BREACH": 50000,
    "FAILURE_TO_SURRENDER": 75000,
    "NO_CURRENT_VACCINATION": 25025,
    "UNLICENSED_ANIMAL": 15075,
}
CITATION_DUE_DAYS = 30

# Surveillance (PRD Section 3.8).
DEFAULT_POSITIVE_THRESHOLD = 3

# Risk scoring reservoir sets (PRD Section 3.1).
HIGH_RISK_WILDLIFE = ["BAT", "RACCOON", "SKUNK", "FOX", "COYOTE"]
DOMESTIC_OBSERVABLE = ["DOG", "CAT", "FERRET"]

# Logical clock startup default (PRD Section 2.5).
CLOCK_START = "2026-03-01T00:00:00Z"
