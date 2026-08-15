"""In-memory data store. Starts completely empty on every boot.

No seeding, no persistence, no disk. The logical clock starts at exactly
2026-08-01T00:00:00Z and is only advanced via POST /_clock/set_current_utc
(PRD §2.4 — the system never consults wall-clock time).
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_CLOCK_DEFAULT)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def parse_iso(s):
    return _parse_iso(s)


def format_iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return format_iso(clock.now())


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Stores — plain dicts keyed by id, all empty at boot. Dict insertion order
# doubles as the creation order used as the tie-break when sorting lists by
# created_at (the logical clock makes created_at ties common).
# ---------------------------------------------------------------------------

vendors = {}
products = {}
entitlements = {}
deployments = {}
positions = {}        # LicensePosition, one per product
audit_cases = {}
scope_items = {}
submissions = {}
offers = {}
remediations = {}
alerts = {}
