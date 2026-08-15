"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding whatsoever.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_NOW = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 timestamp string into an aware UTC datetime."""
    if isinstance(s, datetime):
        dt = s
    else:
        txt = str(s).strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with millisecond precision + Z."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_DEFAULT_NOW)

    def now(self):
        return self._now

    def now_iso(self):
        return _format_iso(self._now)

    def set(self, iso_str):
        self._now = _parse_iso(iso_str)
        return self._now


# ---------------------------------------------------------------------------
# In-memory store — starts EMPTY at every boot (no seeding)
# ---------------------------------------------------------------------------

participants = {}
moderators = {}
studies = {}
applications = {}
nda_agreements = {}
nda_signatures = {}
builds = {}
access_keys = {}
lab_stations = {}
sessions = {}
bookings = {}
instruments = {}
responses = {}
tickets = {}
payouts = {}
breach_cases = {}
exposure_records = {}

clock = LogicalClock()

# Monotonic insertion counter used to break any theoretical ordering ties.
insert_seq = [0]


def next_seq():
    insert_seq[0] += 1
    return insert_seq[0]
