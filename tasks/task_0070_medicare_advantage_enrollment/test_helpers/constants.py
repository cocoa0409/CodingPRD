"""Domain thresholds — numeric constants from PRD calculations (§2.9, §3.7, §3.8, §3.10)."""

# Part D Late Enrollment Penalty: national base beneficiary premium (cents).
NBBP_CENTS = 3470

# Part B Late Enrollment Penalty: standard Part B premium (cents).
PARTB_STD_CENTS = 17470

# Donut-hole drug-phase thresholds (cents), per PRD §3.8.
DEDUCTIBLE_CENTS = 54500
ICL_CENTS = 503000
TROOP_CENTS = 800000

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_OFFSET_MIN = 0

# Medigap guaranteed-issue window length (days), per PRD §3.9.
GI_WINDOW_DAYS = 63
