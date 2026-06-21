"""Domain constants and test defaults for the Dental Practice Management API.

The benefit calculations (§3.8) have no fixed numeric thresholds in the PRD —
the plan parameters (annual maximum, deductible, coinsurance percentages,
waiting/frequency months) are per-InsurancePlan inputs. The values below are the
canonical plan configuration the design indices reuse across instances.
"""

# Canonical insurance-plan configuration used across the design indices.
PLAN_DEFAULTS = {
    "annual_maximum_cents": 100_000,
    "deductible_cents": 5_000,
    "preventive_coinsurance_pct": 100,
    "basic_coinsurance_pct": 80,
    "major_coinsurance_pct": 50,
    "major_waiting_period_months": 0,
    "frequency_limit_months": 0,
}

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}

# Operatory turnover buffer default (PRD §3.1).
DEFAULT_TURNOVER_BUFFER_MINUTES = 15
