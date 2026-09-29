"""Domain thresholds and shared literals drawn from the PRD narrative."""

# PRD §2.5 — the logical clock starts here when no client has ever set it.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §2.12 — states that mandate client trust handling.
TRUST_STATES = ["CA", "FL", "HI", "IA", "WA"]

# PRD §3.2 — the errors-and-omissions floor, one million dollars per occurrence.
MIN_EO_COVERAGE_CENTS = 100_000_000

# PRD §3.5 — the flat channel bonus for an INTERNAL_TOOL booking.
INTERNAL_TOOL_BONUS_PCT = 0.005

# PRD §3.7 — the claim negotiation cycle and its aging thresholds.
MAX_CLAIM_ROUNDS = 3
CLAIM_ESCALATION_DAYS = 60
CLAIM_CRITICAL_DAYS = 120

# PRD §3.7 — receivable aging band edges, both edges inclusive.
AGING_BUCKET_EDGES = [(0, 30), (31, 60), (61, 90), (91, None)]

# PRD §3.1 — chargeback retention defaults to a tenth when omitted.
DEFAULT_CHARGEBACK_RETENTION_PCT = 0.10

# PRD §3.1 — a freshly registered supplier's probation threshold.
DEFAULT_PROBATION_CHARGEBACK_THRESHOLD = 2

# PRD §3.4 — a new client's default aggregate travel capacity.
DEFAULT_MAX_CONCURRENT_TRIPS = 1

# A syntactically valid UUID that never names a row.
MISSING_ID = "00000000-0000-4000-8000-000000000000"

THRESHOLDS = {
    "MIN_EO_COVERAGE_CENTS": MIN_EO_COVERAGE_CENTS,
    "INTERNAL_TOOL_BONUS_PCT": INTERNAL_TOOL_BONUS_PCT,
    "MAX_CLAIM_ROUNDS": MAX_CLAIM_ROUNDS,
    "CLAIM_ESCALATION_DAYS": CLAIM_ESCALATION_DAYS,
    "CLAIM_CRITICAL_DAYS": CLAIM_CRITICAL_DAYS,
}

TEST_DEFAULTS = {
    "GROSS_SALE_CENTS": 1_000_000,
    "TIER_2_FLOOR_CENTS": 5_000_000,
    "TIER_1_ADVISOR_PCT": 0.70,
    "TIER_2_ADVISOR_PCT": 0.80,
    "PLATFORM_FEE_PCT": 0.05,
}
