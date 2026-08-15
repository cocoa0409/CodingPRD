"""In-memory data store and logical clock. Fresh on every process boot
(per-test-server isolation): no seeding, no carry-over state."""
from datetime import datetime, timezone

COLLECTIONS = [
    "publishers",
    "works",
    "rental_sets",
    "customer_accounts",
    "purchase_orders",
    "rental_orders",
    "rental_lines",
    "condition_reports",
    "damage_invoices",
    "perusal_requests",
    "sale_records",
    "rights_cases",
]

db = {name: {} for name in COLLECTIONS}

# Logical clock: starts at exactly 2026-08-01T00:00:00Z; never falls back to
# wall-clock time. Advanced only via POST /library/_clock/set_current_utc.
clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Global monotonic insertion sequence for stable created_at tie-breaking.
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]
