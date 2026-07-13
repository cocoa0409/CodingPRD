"""Domain thresholds — numeric constants from the PHA rent and allocation rules."""

# Preference point schedule (PRD §3.2).
PREFERENCE_POINTS = {
    "VETERAN": 50,
    "ELDERLY": 30,
    "DISABLED": 30,
    "INVOLUNTARY_DISPLACEMENT": 40,
    "LOCAL_RESIDENT": 20,
    "WORKING_FAMILY": 10,
}

# Deductions and rent rates (PRD §3.5).
DEPENDENT_DEDUCTION_ANNUAL_CENTS = 48000
ELDERLY_DISABLED_DEDUCTION_ANNUAL_CENTS = 40000
MEDICAL_THRESHOLD_RATE = 0.03
TTP_ADJ_RATE = 0.30
TTP_GROSS_RATE = 0.10
MINIMUM_RENT_CENTS = 5000

# Allocation thresholds.
REFUSAL_LIMIT = 3          # PRD §3.4 — third refusal purges.
PURGE_STALE_DAYS = 90      # PRD §3.3 — stale purge boundary.
MAKE_READY_DAYS = 14       # PRD §3.4 — make-ready turnaround buffer.

# Logical clock default (PRD §2.9).
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Convenience test defaults.
FAR_FUTURE_EXPIRY = "2026-12-31T00:00:00Z"
HIGH_INCOME_LIMIT_CENTS = 100000000
