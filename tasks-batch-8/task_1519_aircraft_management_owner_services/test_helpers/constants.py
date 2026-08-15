"""Domain thresholds and default values from the PRD (§2.5, §3.3, §3.4)."""

# Logical clock default reading (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Duty limits (PRD §3.3).
DUTY_LIMIT_7D_HOURS = 40.0
DUTY_LIMIT_28D_HOURS = 120.0
MIN_TRAINING_HOURS = 25.0

# Aircraft turnaround buffer in hours (PRD §3.4 scheduling gate 5).
TURNAROUND_BUFFER_HOURS = 1.0

# Budget divisor (PRD §3.8 budget variance).
MONTHS_PER_YEAR = 12

# Standard agreement commercial terms used across setups.
DEFAULT_TERMS = {
    "monthly_management_fee_cents": 500000,
    "variable_fee_pct": 0.10,
    "charter_owner_share_pct": 0.85,
    "tax_allocation_method": "FLIGHT_HOURS",
}

# Standard maintenance program accrual rate.
DEFAULT_PROGRAM_RATE_CENTS = 15000

# A well-formed UUID that never resolves to a created resource.
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
