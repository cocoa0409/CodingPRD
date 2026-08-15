"""Domain thresholds — numeric constants named by the PRD.

Reinstatement fee tiers (PRD §3.7): lapse <= 10 days is free;
10 < lapse <= 30 days costs 2,500 cents; lapse > 30 days costs 5,000 cents.
The lapse flag hardens once more than thirty days pass without reinstatement.
The logical clock starts at 2026-08-01T00:00:00Z before any intervention.
"""

REINSTATEMENT_TIER1_MAX_LAPSE_DAYS = 10
REINSTATEMENT_TIER1_FEE_CENTS = 0
REINSTATEMENT_TIER2_MAX_LAPSE_DAYS = 30
REINSTATEMENT_TIER2_FEE_CENTS = 2500
REINSTATEMENT_TIER3_FEE_CENTS = 5000

LAPSE_FLAG_DAYS = 30

CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Common policy economics used across tests.
DEFAULT_TERM_START = "2026-01-01"
DEFAULT_TERM_END = "2027-01-01"
DEFAULT_TERM_DAYS = 365

# Pagination defaults (PRD §2.3).
PAGE_DEFAULT_LIMIT = 10
PAGE_MAX_LIMIT = 100
