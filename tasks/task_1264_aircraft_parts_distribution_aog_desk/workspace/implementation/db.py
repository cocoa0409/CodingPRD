"""In-memory data store and logical clock. Starts empty on every boot."""

from datetime import datetime, timezone

COLLECTIONS = [
    "customers", "parts", "units", "requests", "quotes", "orders",
    "order_lines", "shipments", "charter_slots", "core_returns", "loans",
    "claims", "rmas", "ledger",
]

store = {c: {} for c in COLLECTIONS}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


class _Clock:
    """Logical clock: starts at exactly 2026-05-01T00:00:00Z, monotonic."""

    def __init__(self):
        self.current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.raw = "2026-05-01T00:00:00Z"


clock = _Clock()

# Monotonic stamp source so entity created_at values are unique per boot.
_last_stamp = [None]


def take_stamp():
    """Return a timestamp >= clock, strictly greater than the last issued one."""
    t = clock.current
    if _last_stamp[0] is not None and t <= _last_stamp[0]:
        from datetime import timedelta
        t = _last_stamp[0] + timedelta(milliseconds=1)
    _last_stamp[0] = t
    return t
