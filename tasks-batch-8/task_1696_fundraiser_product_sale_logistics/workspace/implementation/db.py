"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding, no preloading.
All entity data is created exclusively through the declared API surface.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_START = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 timestamp string into an aware datetime (UTC)."""
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_CLOCK_START)

    def now(self):
        return self._now

    def now_iso(self):
        return _format_iso(self._now)

    def set(self, iso_str):
        self._now = _parse_iso(iso_str)
        return self._now


clock = LogicalClock()


# ---------------------------------------------------------------------------
# In-memory stores (dicts keyed by id)
# ---------------------------------------------------------------------------

campaigns = {}
groups = {}
products = {}
prizes = {}
sellers = {}
orders = {}
order_lines = {}
payments = {}
supplier_orders = {}
supplier_order_lines = {}
distribution_events = {}
sort_tickets = {}
pickup_appointments = {}
claims = {}
return_requests = {}
prize_awards = {}
ledger_entries = {}

# Idempotency: {(endpoint_scope, key): (payload_fingerprint, response_status, response_body)}
idempotency_records = {}
