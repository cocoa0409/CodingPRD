"""Domain thresholds and canonical statute presets (PRD §2.4, §2.6, §3)."""

# PRD §2.4: startup logical clock default.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.1: default contestability window.
DEFAULT_CONTESTABILITY_MONTHS = 24

# PRD §3.8: settlement-election window measured from claim.approved_at.
ELECTION_WINDOW_DAYS = 30

# PRD §3.9: due-diligence lead time before the escheat due date.
DUE_DILIGENCE_LEAD_DAYS = 120

# PRD §2.6: day-count and compounding conventions.
DAYS_PER_YEAR = 365
COMPOUNDS_PER_YEAR = 12
BASIS_POINTS_DENOMINATOR = 10000

# Canonical per-state statute presets used across scenarios (PRD §3.1 inputs).
IL_STATUTE = {
    "state_code": "IL",
    "annual_interest_rate_bp": 1000,
    "interest_basis": "DATE_OF_DEATH",
    "grace_days": 30,
    "payment_deadline_days": 30,
    "dormancy_years": 3,
    "raa_minimum_cents": 100000,
    "raa_annual_interest_rate_bp": 300,
}

NY_STATUTE = {
    "state_code": "NY",
    "annual_interest_rate_bp": 900,
    "interest_basis": "PROOF_OF_LOSS_COMPLETE",
    "grace_days": 15,
    "payment_deadline_days": 30,
    "dormancy_years": 5,
    "raa_minimum_cents": 100000,
    "raa_annual_interest_rate_bp": 300,
}

TX_STATUTE = {
    "state_code": "TX",
    "annual_interest_rate_bp": 1200,
    "interest_basis": "DATE_OF_DEATH",
    "grace_days": 365,
    "payment_deadline_days": 30,
    "dormancy_years": 3,
    "raa_minimum_cents": 100000,
    "raa_annual_interest_rate_bp": 300,
}

STATUTE_PRESETS = {"IL": IL_STATUTE, "NY": NY_STATUTE, "TX": TX_STATUTE}

# Common logical-clock pins used by scenarios.
CLOCK_FILING = "2026-03-05T00:00:00Z"
CLOCK_PROOF = "2026-03-11T00:00:00Z"
CLOCK_APPROVE = "2026-04-10T00:00:00Z"
CLOCK_PAYMENT = "2026-04-01T00:00:00Z"
