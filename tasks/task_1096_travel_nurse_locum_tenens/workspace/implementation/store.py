"""In-memory data store and logical clock. All state is wiped on process boot."""
from datetime import datetime, timezone


DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"


def parse_instant(s):
    """Parse an ISO-8601 UTC instant into an aware datetime (UTC)."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad instant")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_ts(dt):
    """Render an aware datetime as YYYY-MM-DDTHH:MM:SS.mmmZ (exactly 3 frac digits)."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, ms,
    )


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = parse_instant(DEFAULT_CLOCK_UTC)
        self._seq = 0
        self.clinicians = {}
        self.licenses = {}
        self.facilities = {}
        self.per_diem = {}
        self.assignments = {}
        self.contracts = {}
        self.packets = {}
        self.items = {}
        self.timesheets = {}
        self.statements = {}
        self.payroll_runs = {}
        self.extensions = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_ts(self):
        return render_ts(self.clock)

    def clock_date(self):
        return self.clock.date()


store = Store()
