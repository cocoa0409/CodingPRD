"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Per-contributor per-cycle contribution limits, keyed [contributor_type][committee_type] (§3.2).
CONTRIBUTION_LIMIT_CENTS = {
    "INDIVIDUAL": {"CANDIDATE": 330000, "PAC": 500000, "PARTY": 4130000},
    "PAC": {"CANDIDATE": 500000, "PAC": 500000, "PARTY": 1500000},
    "PARTY": {"CANDIDATE": 500000, "PAC": 500000, "PARTY": 0},
    "CORPORATION": {"PAC": 500000},
    "UNION": {"PAC": 500000},
    "FOREIGN_NATIONAL": {},
}

# Public-match calculation (§3.2 / §3.5).
MATCH_RATE = 0.3333333333333333
MATCH_CAP_CENTS = 20000

# Tiered late-filing penalty (§3.6).
BASE_FEE_CENTS = 2500
PER_DAY_RATE_CENTS = {"SMALL": 1000, "MEDIUM": 5000, "LARGE": 20000}
MAX_PENALTY_CENTS = 1000000
SMALL_MAX_CENTS = 500000
MEDIUM_MAX_CENTS = 5000000

# Startup default of the logical clock (§2.5).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
