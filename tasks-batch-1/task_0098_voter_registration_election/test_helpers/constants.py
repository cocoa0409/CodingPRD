"""Domain thresholds — numeric constants from the PRD's calculations (§3.9)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

# Calculation thresholds named verbatim in the PRD.
THRESHOLDS = {
    "VOTING_AGE": 18,            # §3.9 age eligibility: must be at least 18.
    "DISCREPANCY_TOLERANCE": 5,  # §3.9 recount certification: delta <= 5 is within tolerance.
    "ROUND_DP": 2,              # §2.7 turnout percentages reported to two decimal places.
}

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Reusable election timing template used by most fixtures. Clocks are set
# per-fixture; these are the election's declared deadlines/windows.
ELECTION_DEFAULTS = {
    "name": "Gen26",
    "election_date": "2026-11-03T20:00:00Z",
    "registration_deadline": "2026-10-01T00:00:00Z",
    "absentee_request_deadline": "2026-10-20T00:00:00Z",
    "cure_deadline": "2026-11-10T00:00:00Z",
    "early_voting_start": "2026-10-15T00:00:00Z",
    "early_voting_end": "2026-11-02T00:00:00Z",
}

# A UUID that is well-formed but never minted by the server.
MISSING_UUID = NON_EXISTENT_UUID
