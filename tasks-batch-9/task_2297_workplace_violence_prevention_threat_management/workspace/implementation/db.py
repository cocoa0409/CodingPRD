"""In-memory data store and the logical clock.

The store starts completely empty on every boot: no entity is seeded, preloaded,
registered or hardcoded here.  Every row a test needs is created through the
declared API surface.
"""

import itertools
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.9: before any client sets it, the logical clock reads exactly this.
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"

UTC = timezone.utc


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_ms(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_dt(dt):
    """Format a logical-clock instant the way the logical clock itself reads.

    PRD 2.9 pins the clock at exactly ``2026-08-01T00:00:00Z``, so an instant
    derived from the clock renders in that same shape and only carries a
    fractional part when it actually has one.
    """
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        )
    return fmt_ms(dt)


_last_ms = [0]
_wall_lock = threading.Lock()


def real_now_iso():
    """Wall-clock timestamp for created_at / updated_at, strictly increasing.

    Strict monotonicity matters: plan_revision and prior_case_count are defined
    in terms of "rows created earlier than this one".
    """
    with _wall_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms[0]:
            ms = _last_ms[0] + 1
        _last_ms[0] = ms
    return fmt_ms(datetime.fromtimestamp(ms / 1000.0, UTC))


class Store(object):
    def __init__(self):
        self.worksites = {}
        self.work_areas = {}
        self.prevention_plans = {}
        self.hazard_assessments = {}
        self.employees = {}
        self.training_modules = {}
        self.training_assignments = {}
        self.incident_reports = {}
        self.threat_cases = {}
        self.team_assignments = {}
        self.case_actions = {}
        self.log_entries = {}
        self.drills = {}
        self.clock_raw = DEFAULT_CLOCK_RAW
        self.clock = parse_dt(DEFAULT_CLOCK_RAW)
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def set_clock(self, raw, dt):
        self.clock_raw = raw
        self.clock = dt


store = Store()

# Serialises request handling so the in-memory dicts never interleave.
request_lock = threading.RLock()


def now():
    """Current logical clock instant (aware UTC datetime)."""
    return store.clock


def now_raw():
    """Current logical clock rendered exactly as the client supplied it."""
    return store.clock_raw


def new_id():
    return str(uuid.uuid4())


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def plus_years(dt, years):
    """Add whole calendar years, clamping 29 Feb to 28 Feb."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def new_row(fields):
    """Build a row with the shared system fields (id / created_at / updated_at / version)."""
    stamp = real_now_iso()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def new_log_row(fields):
    """ViolentIncidentLogEntry carries only id and created_at (no updated_at/version)."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = real_now_iso()
    row["_seq"] = store.next_seq()
    return row


def in_order(rows):
    """Deterministic ascending creation order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
