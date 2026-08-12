"""In-memory data store, logical clock, and entity helpers."""
import uuid
from datetime import datetime, date, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.seq = 0
        self.clock = DEFAULT_CLOCK
        self.clock_raw = "2026-05-01T00:00:00Z"
        self.profile = None
        self.aircraft = {}
        self.vehicles = {}
        self.readiness_checks = {}
        self.firefighters = {}
        self.training_records = {}
        self.drills = {}
        self.determinations = {}
        self.incidents = {}
        self.agreements = {}
        self.requests = {}
        self.oos_events = {}
        self.notifications = {}
        self.reports = {}
        self.reviews = {}
        self.inspections = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Render a logical-clock stamp the way the clock itself reads (PRD §2.5:
    the clock reads exactly e.g. 2026-05-01T00:00:00Z). Fractional digits
    appear only when the clock value itself carries them."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += "." + f"{dt.microsecond // 1000:03d}"
    return base + "Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string; returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO date string YYYY-MM-DD; returns date or None."""
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def month_index(d):
    """year * 12 + month (month in 1..12). Accepts date or datetime."""
    return d.year * 12 + d.month


def base_entity():
    now = fmt_ts(store.clock)
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = fmt_ts(store.clock)
    entity["version"] += 1


def serialize(entity):
    """Public view: strip internal underscore-prefixed keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
