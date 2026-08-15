"""Domain thresholds and constants from the PRD.

Grade values (PRD §3.2): A=4.00, B=3.00, C=2.00, D=1.00, F=0.00, W has no value.
Filing lead time (PRD §3.6): submit no later than 30 days before the conferral date.
Logical clock default (PRD §2.5): 2026-08-01T00:00:00Z before any adjustment.
Honors residency default (PRD §3.1/§3.7): 30 institutional earned credits.
Pagination defaults (PRD §2.3): limit defaults to 10, offset defaults to 0.
"""

GRADE_VALUES = {
    "A": 4.00,
    "B": 3.00,
    "C": 2.00,
    "D": 1.00,
    "F": 0.00,
}

PASSING_GRADES = ("A", "B", "C", "D")

THRESHOLDS = {
    "FILING_LEAD_DAYS": 30,
    "DEFAULT_RESIDENCY_MIN_CREDITS": 30,
}

PAGINATION_DEFAULTS = {
    "limit": 10,
    "offset": 0,
    "min_limit": 1,
    "max_limit": 100,
}

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "EXPECTED_TERM": "2026-SP",
    # A conferral date comfortably more than 30 days after the default clock
    # (2026-08-01), so filing succeeds without clock manipulation.
    "EXPECTED_CONFERRAL_DATE": "2026-09-15",
    "COURSE_CREDITS": 3,
}

# A well-formed UUID that no created resource will ever have.
ABSENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
