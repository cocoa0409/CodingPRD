"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Compatibility score weights and the accept gate threshold (PRD §3.1, §3.2).
COMPAT = {
    "W_CLEAN": 40,
    "W_SLEEP": 30,
    "W_LIFESTYLE": 30,
    "MATCH_THRESHOLD": 60,
}

# A fixed non-existent UUID used for 404 / existence tests.
MISSING_UUID = "00000000-0000-0000-0000-000000000000"

# Default profile attributes used by setup helpers.
DEFAULT_INCOME_CENTS = 500_000
