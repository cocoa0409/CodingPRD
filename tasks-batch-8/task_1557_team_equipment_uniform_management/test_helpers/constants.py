"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD: the logical clock section).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Standard season label used across tests unless overridden.
DEFAULT_SEASON = "2026-FALL"

THRESHOLDS = {
    # Damage fee clamps (PRD loss/damage section): floor then ceiling.
    "DEDUCTIBLE_CENTS": 5000,
    "FEE_CAP_CENTS": 50000,
    # Reconditioning window length in days; due_back_on = sent_on + 45 days.
    "RECONDITIONING_SLA_DAYS": 45,
    # Certification validity granted by a passed reconditioning, in days.
    "CERT_VALIDITY_DAYS": 365,
    # Laundry turnaround budget after kickoff, in hours.
    "LAUNDRY_TURNAROUND_HOURS": 48,
    # Maximum ALTERNATE-kit games per season (strictly fewer may pre-exist).
    "MAX_ALTERNATE_KIT_GAMES_PER_SEASON": 3,
    # Minimum gap between same-season non-cancelled kickoffs, in hours.
    "MIN_EVENT_SPACING_HOURS": 48,
    # Maximum overlapping open reconditioning jobs per provider.
    "MAX_CONCURRENT_JOBS_PER_PROVIDER": 2,
}

# Damage fee condition factors per assessed grade (PRD loss/damage section).
CONDITION_FACTORS = {"A": 1.00, "B": 0.80, "C": 0.60, "F": 0.25}
