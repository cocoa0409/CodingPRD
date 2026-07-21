"""Domain thresholds and default test values from the PRD.

The three named windows are declared verbatim in the PRD with concrete values:
- RESCISSION_WINDOW_DAYS = 3 days   (PRD §3.2)
- SUPPLEMENT_WINDOW_DAYS = 365 days (PRD §3.6)
- TRAVEL_BUFFER_MINUTES = 60 minutes (PRD §3.3)
"""

RESCISSION_WINDOW_DAYS = 3
SUPPLEMENT_WINDOW_DAYS = 365
TRAVEL_BUFFER_MINUTES = 60

# Default clock at server startup (PRD §2.11).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Common test values reused across fixtures.
TEST_DEFAULTS = {
    "COVERAGE_LIMIT_CENTS": 100_000_000,
    "DEDUCTIBLE_CENTS": 100_000,
    "FEE_PCT": 0.10,
    "STATUTORY_CAP_PCT": 0.10,
    "RCV_ESTIMATE_CENTS": 10_000_000,
    "DEPRECIATION_PCT": 0.20,
    "POLICY_EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "POLICY_EXPIRY_DATE": "2027-01-01T00:00:00Z",
    "LICENSE_EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "LICENSE_EXPIRY_DATE": "2027-01-01T00:00:00Z",
    "DATE_OF_LOSS": "2026-06-15T00:00:00Z",
}
