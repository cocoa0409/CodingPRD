"""In-memory data store and the single logical clock.

The store starts completely empty on every boot. Nothing is seeded here or
anywhere else: every entity is created through the declared API surface.
"""

from datetime import datetime, timezone

STORE_KEYS = [
    "funders",
    "grants",
    "budget_lines",
    "funds",
    "expenses",
    "allocations",
    "reports",
    "variance_explanations",
    "match_contributions",
    "modification_requests",
    "audit_engagements",
    "audit_findings",
    "renewal_applications",
]

store = {k: {} for k in STORE_KEYS}

# The logical clock. Boots pinned to exactly 2026-05-01T00:00:00Z and never
# falls back to wall-clock time.
_clock = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


_order_counter = {"n": 0}


def next_order():
    """Monotonic insertion counter used as a stable created_at tie-breaker."""
    _order_counter["n"] += 1
    return _order_counter["n"]
