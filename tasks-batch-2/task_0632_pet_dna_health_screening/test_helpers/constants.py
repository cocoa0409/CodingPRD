"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Genotyping QC score weights and gates (PRD §3.3).
QC_WEIGHTS = {
    "W_CALL": 0.6,
    "W_CONTAM": 0.3,
    "W_HET": 0.1,
    "HET_TARGET": 0.35,
    "CALL_GATE": 0.85,
    "QC_QNS_FLOOR": 60.00,
}

# Breed ancestry composition (PRD §3.4).
BREED_TARGET_SUM = 100.00

# Subscription upgrade proration (PRD §3.7).
PREMIUM_ANNUAL_FEE_CENTS = 19900
PRORATION_FLOOR_CENTS = 0

# Relative kinship (PRD §3.6).
TOTAL_AUTOSOMAL_CM = 2500.0
PHASE_FACTOR = 0.98

# Temporal windows.
DELETE_GRACE_DAYS = 30
DEFAULT_TERM_DAYS = 365

# Clock default at server startup (PRD §2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASIC_FEE_CENTS": 9900,
    "PREMIUM_FEE_CENTS": 19900,
}
