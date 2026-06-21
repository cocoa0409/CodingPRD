"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework; not re-defined here.
"""

# Milliseconds in a UTC day — aging day count (PRD §3.2).
DAY_MS = 86_400_000

# Watch threshold percentage of credit limit (PRD §2.7 / §3.1).
CREDIT_WATCH_PCT = 0.80

# Statement finance-charge monthly rate (PRD §3.8).
MONTHLY_RATE = 0.015

# Conservative-forecast collection probability by due-date-basis aging bucket
# (PRD §3.9).
COLLECT_PROB = {
    "CURRENT": 1.0,
    "B1_30": 0.90,
    "B31_60": 0.70,
    "B61_90": 0.40,
    "B91_PLUS": 0.10,
}

# Priority-score weights (PRD §3.7).
W_BAL = 1.0
W_AGE = 2.0
W_STAGE = 1.5
W_PTP = 3.0
AGE_WEIGHT = {"CURRENT": 0.0, "B1_30": 1.0, "B31_60": 2.0, "B61_90": 3.0, "B91_PLUS": 4.0}
STAGE_WEIGHT = {"CURRENT": 0.0, "DUNNING": 1.0, "COLLECTIONS": 2.0, "WRITEOFF": 0.0}

# Pagination bounds (PRD §2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}

# A well-formed UUID that is never minted by the server — for not-found probes.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
