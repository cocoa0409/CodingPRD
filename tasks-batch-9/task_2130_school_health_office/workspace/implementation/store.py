"""In-memory data store, logical clock and common-field helpers.

Storage is process-local Python dicts only.  Nothing is persisted; a fresh
process starts with a completely empty store.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# The logical clock reads exactly this instant before any client moves it.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "schools",
    "nurses",
    "coverage_assignments",
    "students",
    "action_plans",
    "medication_authorizations",
    "medication_stock_lots",
    "health_visits",
    "administration_records",
    "screenings",
    "disclosure_requests",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self.epoch = 0
        self._seq = 0
        self.touched = set()

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- clock -------------------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, value):
        previous = self.clock
        self.clock = value
        return previous


db = Store()


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)


def minute_of_day(dt):
    dt = dt.astimezone(UTC)
    return dt.hour * 60 + dt.minute


WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def weekday_name(dt):
    return WEEKDAY_NAMES[dt.astimezone(UTC).weekday()]


def utc_day_start(dt):
    dt = dt.astimezone(UTC)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def same_utc_day(a, b):
    if a is None or b is None:
        return False
    return utc_day_start(a) == utc_day_start(b)


def floor_minutes(delta):
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------------
# record helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def new_record(fields):
    now = db.now()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    record.update(fields)
    record["_seq"] = db.next_seq()
    return record


def touched_set():
    try:
        from flask import g, has_request_context
        if has_request_context():
            if not hasattr(g, "touched_records"):
                g.touched_records = set()
            return g.touched_records
    except Exception:
        pass
    return db.touched


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version once per
    request, so a multi-hop cascade advances each touched record exactly once."""
    if record is None:
        return
    seen = touched_set()
    key = id(record)
    if key in seen:
        return
    seen.add(key)
    record["updated_at"] = db.now()
    record["version"] = record.get("version", 0) + 1


def sorted_rows(rows):
    """Default ordering: created_at ascending, insertion order as the stable
    tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
