"""In-memory data store + logical clock.

The store starts empty on every boot — no seeding. The logical clock starts at
exactly 2026-08-01T00:00:00Z and only advances via POST /_clock/set_current_utc;
it never falls back to wall time.
"""

from datetime import datetime, timezone


def _parse_iso(s):
    """Parse an ISO-8601 datetime string (accepts trailing Z) to aware UTC datetime."""
    if isinstance(s, str):
        s = s.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware UTC datetime as ISO-8601 with exactly three fractional digits, Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # Entity tables, keyed by id. All start empty.
        self.donors = {}
        self.bikes = {}
        self.parts = {}
        self.part_harvests = {}
        self.part_usages = {}
        self.volunteers = {}
        self.training_sessions = {}
        self.attendances = {}
        self.shifts = {}
        self.participants = {}
        self.hour_logs = {}
        self.sales = {}
        self.giveaways = {}
        self.inspections = {}
        self.memberships = {}
        self.tool_sessions = {}
        self.scrap_tickets = {}
        self.helmet_distributions = {}
        # Logical clock — startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_ts(self.clock)

    def today(self):
        return self.clock.date()


db = Store()
