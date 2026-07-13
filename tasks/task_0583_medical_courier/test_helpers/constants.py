"""Domain thresholds and canonical test values from the PRD's workflows (§3)."""

# Service-level deadlines (PRD §3.2): scheduled_start + 120 min (STAT) / 480 min (SCHEDULED).
SLA_MINUTES = {
    "STAT": 120,
    "SCHEDULED": 480,
}

# Specimen risk bases by specimen_type (PRD §3.5).
SPECIMEN_BASE_RISK = {
    "BLOOD": 10,
    "TISSUE": 20,
    "URINE": 5,
    "SWAB": 5,
    "CULTURE": 15,
}

# Risk-scoring constants (PRD §3.5).
EXCURSION_PENALTY = 25
RISK_TIME_DIVISOR_MINUTES = 10

# Canonical rate card used across the suite (PRD §3.1 fee fields).
TEST_DEFAULTS = {
    "PER_STOP_FEE_CENTS": 500,
    "PER_MILE_RATE_CENTS": 133,
    "STAT_SURCHARGE_PCT": 0.30,
    "STAT_SURCHARGE_CAP_CENTS": 10_000,
    "TEMP_HANDLING_FEE_CENTS": 800,
    "LAB_BUDGET_CENTS": 100_000,
    "SANITATION_BUFFER_MINUTES": 30,
    "PLANNED_TOTAL_MILES": 6.0,
}

# Canonical clock instants (PRD §2.9 — the clock starts at 2026-05-01T00:00:00Z).
CLOCK_DEFAULT_STARTUP = "2026-05-01T00:00:00Z"
CLOCK_BEFORE_RUN = "2026-05-05T08:00:00Z"
CLOCK_DURING_RUN = "2026-05-05T09:15:00Z"

# Canonical route window: 09:00 -> 11:00 (a 120-minute planned transit).
ROUTE_START = "2026-05-05T09:00:00Z"
ROUTE_END = "2026-05-05T11:00:00Z"

# Credential expiry far beyond every clock instant the suite sets.
CREDENTIAL_VALID_UNTIL = "2026-12-31T00:00:00Z"
