import re
import uuid
from datetime import datetime, timezone


class LogicalClock:
    """Single logical clock. Startup default exactly 2026-08-01T00:00:00Z.
    Never falls back to wall-clock time."""

    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = LogicalClock()

STORE = {
    "buildings": {},
    "key_nodes": {},
    "doors": {},
    "persons": {},
    "credentials": {},
    "access_groups": {},
    "access_events": {},
    "propped_alerts": {},
    "incidents": {},
    "campaigns": {},
    "work_orders": {},
    "charges": {},
}

SEQ_COUNTERS = {}  # (building_id, kind) -> int


def next_seq(building_id, kind):
    key = (building_id, kind)
    SEQ_COUNTERS[key] = SEQ_COUNTERS.get(key, 0) + 1
    return SEQ_COUNTERS[key]


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(s):
    """Parse an ISO 8601 timestamp to an aware UTC datetime; None on failure."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    try:
        if t.endswith("Z") or t.endswith("z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_hhmm(s):
    """Parse HH:MM to minutes since 00:00; None on failure."""
    if not isinstance(s, str):
        return None
    m = _HHMM_RE.match(s.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def norm_hhmm(s):
    mins = parse_hhmm(s)
    if mins is None:
        return None
    return "%02d:%02d" % (mins // 60, mins % 60)


def bump(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["version"] += 1
    entity["updated_at"] = CLOCK.now()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)
