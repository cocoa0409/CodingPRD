"""In-memory data store and the logical clock.

The store starts completely EMPTY on every boot — no seeding whatsoever. All
state is built by tests through the declared API surface. The only startup
constant is the logical clock default required by PRD section 2.5
("At startup the clock reads exactly 2026-08-01T00:00:00Z").
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.5)
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


def _format_iso_business(dt):
    """Format business-law datetimes: omit the fractional part when zero.

    Computed statutory datetimes (opposition_due_at, computed_due_at,
    response_due_at, maintenance windows, ...) are asserted in whole-second
    form, e.g. "2026-08-14T09:00:00Z"; sub-second values keep milliseconds.
    """
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return f"{base}.{dt.microsecond // 1000:03d}Z"
    return f"{base}Z"


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
# In-memory stores — all start EMPTY at every boot
# ---------------------------------------------------------------------------

clients = {}
trademark_records = {}
watch_alerts = {}
enforcement_matters = {}
deadlines = {}
cease_desist_letters = {}
takedown_filings = {}
coexistence_agreements = {}
evidence_items = {}
maintenance_filings = {}
clearance_searches = {}
customs_recordations = {}
counterfeit_referrals = {}

clock = LogicalClock()

# Monotonic insertion counter used to break ordering ties on created_at.
insert_seq = [0]


def next_seq():
    insert_seq[0] += 1
    return insert_seq[0]
