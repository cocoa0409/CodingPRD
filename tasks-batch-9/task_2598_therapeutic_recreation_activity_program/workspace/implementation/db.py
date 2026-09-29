"""In-memory data store, logical clock, and time helpers.

Storage is process-local dictionaries keyed by entity id. The store boots
completely empty: no entity is ever seeded, preloaded or hardcoded.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class Store(object):
    COLLECTIONS = (
        "residents",
        "assessments",
        "plans",
        "programs",
        "rooms",
        "sessions",
        "participation",
        "volunteers",
        "assignments",
        "vehicles",
        "outings",
        "consents",
        "council_requests",
        "packets",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return iso(self.clock)

    def today(self):
        return self.clock.date()


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 instant in UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_datetime(value):
    """Strict ISO 8601 instant parse. Returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Strict YYYY-MM-DD parse. Returns date or None."""
    if not isinstance(value, str):
        return None
    if not _DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def date_str(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_days(d, days):
    return d + timedelta(days=days)


def overlaps(a_lo, a_hi, b_lo, b_hi):
    """Half-open [lo, hi) intersection test. Touching intervals do not."""
    return a_lo < b_hi and b_lo < a_hi


class Ctx(object):
    """Per-request mutation tracker.

    Every entity a request (or one of its cascades) mutates has its
    updated_at refreshed and its version advanced exactly once.
    """

    def __init__(self, st):
        self.st = st
        self.touched = set()

    def bump(self, obj):
        if obj is None:
            return
        key = obj.get("id")
        if key in self.touched:
            return
        self.touched.add(key)
        if "version" in obj:
            obj["version"] = obj.get("version", 1) + 1
        if "updated_at" in obj:
            obj["updated_at"] = self.st.now_iso()

    def set_fields(self, obj, values):
        """Apply derived values; advance version only when something moved."""
        changed = False
        for key, value in values.items():
            if obj.get(key) != value:
                obj[key] = value
                changed = True
        if changed:
            self.bump(obj)
        return changed


def require(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)
