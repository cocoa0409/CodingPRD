"""Domain thresholds and shared values from the PRD."""

# PRD §2.5 — the logical clock reads exactly this instant before any explicit set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.8 — return-credit restock rates and windows.
RETURN_CREDIT = {
    "COLD_CHAIN_WINDOW_DAYS": 2,        # cold chain: half credit within 2 days
    "FULL_CREDIT_WINDOW_DAYS": 30,      # other product: full credit within 30 days
    "PARTIAL_CREDIT_WINDOW_DAYS": 90,   # four-fifths credit days 31..90
    "PARTIAL_CREDIT_RATE": 0.80,
    "COLD_CHAIN_RATE": 0.50,
}

# PRD §3.8 — cold-chain returns must be lodged within 48 hours of delivery.
COLD_RETURN_WINDOW_HOURS = 48

# PRD §3.6 — a cleared investigation may be reopened while reopen_count < 3.
REOPEN_LIMIT = 3

# Common validity window for licenses used across tests.
LICENSE_VALID_FROM = "2026-01-01T00:00:00Z"
LICENSE_VALID_TO = "2027-01-01T00:00:00Z"

# Far-future lot expiry so cases are shippable at the default clock.
CASE_EXPIRY = "2027-01-01T00:00:00Z"

# Generous credit limit for scenarios where credit enforcement is not under test.
HIGH_CREDIT_LIMIT = 100_000_000
