"""In-memory data store. Empty on every boot; no seeding, no persistence.

Logical clock default per PRD §2.4: exactly 2026-08-01T00:00:00Z before any
set call; never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 instant, accepting trailing 'Z'. Returns aware UTC datetime."""
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


def iso_out(dt):
    """Render aware UTC datetime as ISO 8601 with three fractional digits and Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def now_iso():
    return iso_out(datetime.now(timezone.utc))


class Store:
    def __init__(self):
        self.routes = {}              # id -> dict
        self.vessels = {}
        self.fare_schedules = {}
        self.sailings = {}
        self.customers = {}
        self.bookings = {}
        self.standby_entries = {}
        self.crew_members = {}
        self.crew_assignments = {}
        # Logical clock (PRD §2.4)
        self.current_utc = _parse_iso(DEFAULT_CLOCK_ISO)

    def new_id(self):
        return str(uuid.uuid4())


db = Store()
