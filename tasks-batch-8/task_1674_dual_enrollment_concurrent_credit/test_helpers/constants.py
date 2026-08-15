"""Domain thresholds and reusable scenario constants (PRD 2.4, 2.7, 3.x)."""

# Logical clock startup default (PRD 3.10).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Placement validity window in days (PRD 3.2).
PLACEMENT_VALIDITY_DAYS = 730

# Refund percentages (PRD 2.7, 3.5, 3.7).
DROP_REFUND_PCT = 100
MISMATCH_REFUND_PCT = 50
PLAIN_WITHDRAW_REFUND_PCT = 0

# GPA scales (PRD 3.8).
COLLEGE_SCALE = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
HS_SCALE = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 0, "W": 0}

# Standard calendar pair used by most scenarios (PRD 2.4 two-calendar discipline).
COLLEGE_TERM_DEFAULTS = {
    "institution_type": "COLLEGE",
    "name": "Fall 2026 College",
    "start_date": "2026-08-15T00:00:00Z",
    "end_date": "2026-12-15T00:00:00Z",
    "add_deadline": "2026-09-01T00:00:00Z",
    "drop_deadline": "2026-09-15T00:00:00Z",
    "withdraw_deadline": "2026-11-01T00:00:00Z",
}

HS_TERM_DEFAULTS = {
    "institution_type": "HIGH_SCHOOL",
    "name": "Fall 2026 HS",
    "start_date": "2026-08-20T00:00:00Z",
    "end_date": "2026-12-20T00:00:00Z",
    "add_deadline": "2026-09-05T00:00:00Z",
    "drop_deadline": "2026-09-10T00:00:00Z",
    "withdraw_deadline": "2026-10-25T00:00:00Z",
}

# Standard STATE_PROGRAM funding terms: 40000/cr tuition, 30000/cr state, cap 0.
STANDARD_FUNDING_DEFAULTS = {
    "funding_model": "STATE_PROGRAM",
    "tuition_cents_per_credit": 40000,
    "state_rate_cents_per_credit": 30000,
    "district_cap_cents": 0,
}

# Common clock instants exercised across scenarios.
CLOCK_IN_MISMATCH_WINDOW = "2026-09-12T00:00:00Z"  # after HS drop, at/before college drop
CLOCK_AFTER_ALL_DROP_DEADLINES = "2026-09-20T00:00:00Z"  # past both drop deadlines
CLOCK_AFTER_HS_WITHDRAW = "2026-10-26T00:00:00Z"  # past min withdraw deadline
CLOCK_AFTER_COLLEGE_END = "2026-12-16T00:00:00Z"  # past college term end
CLOCK_BEFORE_COLLEGE_END = "2026-12-01T00:00:00Z"  # before college term end
