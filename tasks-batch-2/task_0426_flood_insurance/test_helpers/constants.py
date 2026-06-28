"""Domain thresholds — numeric constants from the Flood Insurance premium and
settlement calculations. Generic NON_EXISTENT_UUID comes from the framework."""

# CRS Community Rating System discount table: crs_class -> discount fraction.
CRS_DISCOUNT_TABLE = {
    1: 0.45,
    2: 0.40,
    3: 0.35,
    4: 0.30,
    5: 0.25,
    6: 0.20,
    7: 0.15,
    8: 0.10,
    9: 0.05,
    10: 0.00,
}

# Risk Rating 2.0 rates.
BUILDING_RATE_RR2 = {"HIGH": 0.0040, "MODERATE": 0.0025, "LOW": 0.0012}
CONTENTS_RATE_RR2 = 0.0020
# Flood-zone -> RR2 rate band.
RR2_ZONE_BAND = {"VE": "HIGH", "AE": "MODERATE", "X": "LOW"}

# Legacy subsidized rates keyed on flood zone.
BUILDING_RATE_LEGACY = {"AE": 0.0060, "VE": 0.0090, "X": 0.0010}
CONTENTS_RATE_LEGACY = {"AE": 0.0035, "VE": 0.0050, "X": 0.0008}

# Flat premium components.
ICC_PREMIUM = 75
FEDERAL_POLICY_FEE = 50
HFIAA_PRIMARY = 25
HFIAA_NONPRIMARY = 250

# Coverage caps and deductible set.
BUILDING_COVERAGE_CAP = 250000
CONTENTS_COVERAGE_CAP = 100000
ALLOWED_DEDUCTIBLES = {1000, 2000, 5000, 10000}
DEFAULT_BUILDING_DEDUCTIBLE = 2000
DEFAULT_CONTENTS_DEDUCTIBLE = 1000

# Claim settlement.
ICC_COVERAGE_CAP = 30000

# Waiting period / term.
STANDARD_WAITING_DAYS = 30
LENDER_WAITING_DAYS = 0
TERM_DAYS = 365

# Proof-of-loss deadline.
PROOF_OF_LOSS_DEADLINE_DAYS = 60

# Repetitive-loss threshold.
REPETITIVE_LOSS_THRESHOLD = 2

# Logical-clock startup default.
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"
