"""Domain thresholds and pinned constants named by the PRD."""

THRESHOLDS = {
    # Duplicate screening: billed charges may differ by at most five dollars,
    # applied inclusively.
    "DUP_BILLED_TOLERANCE_CENTS": 500,
    # DENY-severity rules at or below this precedence rank are hard denials.
    "HARD_DENY_RANK_MAX": 10,
    # Contract windows for the same provider-and-plan pair need at least one
    # full clear calendar day between them.
    "CONTRACT_GAP_DAYS": 1,
    # Pagination bounds.
    "PAGINATION_LIMIT_MIN": 1,
    "PAGINATION_LIMIT_MAX": 100,
    "PAGINATION_LIMIT_DEFAULT": 10,
    "PAGINATION_OFFSET_DEFAULT": 0,
}

PLAN_DEFAULTS = {
    "plan_year_start_date": "2026-01-01",
    "copay_office_visit_cents": 2500,
    "out_of_network_penalty_pct": 0.30,
    "timely_filing_days": 90,
    "cob_method": "COME_OUT_WHOLE",
}

MEMBER_DEFAULTS = {
    "first_name": "Given",
    "last_name": "Family",
    "date_of_birth": "1980-01-01",
}

PROVIDER_DEFAULTS = {
    "specialty_code": "GEN",
}

COVERAGE_DEFAULTS = {
    "term_date": None,
    "other_payer_name": None,
    "coverage_tier": "INDIVIDUAL",
}

# Office-visit procedure codes that take a flat copay instead of a deductible draw.
COPAY_PROCEDURE_CODES = ["99213", "99214"]

# The logical clock reads exactly this instant before it has ever been set.
DEFAULT_LOGICAL_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"

# Clock value the majority of scenarios pin so date arithmetic is deterministic.
TEST_CLOCK_ISO = "2026-03-01T00:00:00Z"
TEST_CLOCK_STAMP = "2026-03-01T00:00:00.000Z"

TEST_DEFAULTS = {
    "DEDUCTIBLE_CENTS": 50000,
    "OOP_MAX_CENTS": 300000,
    "COINSURANCE_PCT": 0.20,
    "OPEN_OOP_MAX_CENTS": 1000000,
    "RATE_IMAGING_CENTS": 40000,
    "RATE_OFFICE_VISIT_CENTS": 10000,
}

# Well-formed UUIDs that never resolve to a row.
UNKNOWN_UUIDS = [
    "00000000-0000-4000-8000-000000000000",
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
    "00000000-0000-4000-8000-000000000004",
    "00000000-0000-4000-8000-000000000005",
    "00000000-0000-4000-8000-000000000006",
    "00000000-0000-4000-8000-000000000007",
    "00000000-0000-4000-8000-000000000008",
    "00000000-0000-4000-8000-000000000009",
]
