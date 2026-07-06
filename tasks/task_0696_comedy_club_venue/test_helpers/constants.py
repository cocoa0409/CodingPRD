"""Domain thresholds — numeric constants from the PRD's calculation rules."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

# A well-formed UUID that resolves to no entity (for 404 tests).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

THRESHOLDS = {
    # §3.4 — venue-wide per-seat item/drink minimum default.
    "VENUE_DEFAULT_MIN_ITEMS": 2,
    # §3.4 — each required item is valued at 1000 cents of consumption.
    "MIN_ITEM_UNIT_PRICE_CENTS": 1000,
    # §3.7 — flat patron cancellation fee retained inside the late window.
    "CANCEL_FEE_CENTS": 1500,
    # §3.7 — late-cancel grace window (minutes before starts_at).
    "LATE_CANCEL_GRACE_MINUTES": 120,
    # §3.9 — contract negotiation loop cap.
    "MAX_COUNTER_ROUNDS": 3,
    # §3.1 — default house cut fraction of gross box-office.
    "DEFAULT_HOUSE_FEE_PCT": 0.20,
    # §3.2 / §3.3 — default per-seat minimum and server table cap.
    "DEFAULT_MIN_ITEMS_PER_SEAT": 2,
    "DEFAULT_MAX_TABLES": 4,
    # §3.11 — default buyout deposit fraction.
    "DEFAULT_DEPOSIT_PCT": 0.25,
    # §2.7 — startup logical clock instant.
    "CLOCK_STARTUP": "2026-03-01T00:00:00Z",
    # §2.3 — pagination bounds.
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MAX_LIMIT": 100,
    "PAGINATION_MIN_LIMIT": 1,
}
