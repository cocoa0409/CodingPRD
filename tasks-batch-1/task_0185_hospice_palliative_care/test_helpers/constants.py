"""Domain thresholds — numeric constants from the hospice & palliative care PRD."""

# Per-diem rate table (cents/day), PRD §3.6.
PER_DIEM = {
    "ROUTINE_HIGH_CENTS": 21000,   # $210.00/day, first 60 elapsed days
    "ROUTINE_BASE_CENTS": 16500,   # $165.00/day, day 61 onward
    "RESPITE_CENTS": 47000,        # $470.00/day inpatient respite
    "GIP_CENTS": 110000,           # $1,100.00/day general inpatient
}

# Benefit-period cadence, PRD §3.3.
PERIOD = {
    "PERIOD_1_2_LENGTH": 90,
    "PERIOD_3_PLUS_LENGTH": 60,
    "ROUTINE_HIGH_DAYS": 60,       # elapsed-day window for the high tier
}

# Respite consecutive-day limit, PRD §3.7.
RESPITE_MAX_CONSECUTIVE = 5

# Cap window, PRD §3.1 / §3.11.
CAP_WINDOW_DAYS = 365

# Common test default for a provider's per-beneficiary cap (a large value that
# leaves a single test election well under cap so liability stays 0).
DEFAULT_PER_BENEFICIARY_CAP_CENTS = 3490000  # $34,900.00
