"""Domain thresholds — numeric constants from PRD calculations (§2.8, §3.1, §3.2, §3.3)."""

# Dependent filing threshold: a DEPENDENT_NONFILER below this is excluded from MAGI.
FILING_THRESHOLD_CENTS = 1_460_000  # $14,600

# Federal Poverty Level annual figure (cents).
FPL_BASE_CENTS = 1_500_000  # $15,000 for a household of one
FPL_ADDL_CENTS = 530_000    # +$5,300 per additional person

# Applicable-percentage cap (ARPA: no 400% cliff).
CAP_RATE = 0.085

# SEP filing window length (calendar days after event_date).
SEP_WINDOW_DAYS = 60

# Loss-of-coverage effective-date cutoff day.
REGULAR_CUTOFF_DAY = 15

# CSR Plus top tier label.
CSR_PLUS_TIER = "CSR94"
