"""In-memory data store (PRD 2.4 common properties, 2.5 logical clock).

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded. All state is created through the declared API surface.
"""
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# PRD 2.5: the logical clock starts at exactly this instant on every boot and
# never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _ISO_RE.match(text)
    if not m:
        # bare calendar date
        try:
            d = datetime.strptime(text, "%Y-%m-%d")
            return d.replace(tzinfo=UTC)
        except ValueError:
            return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.agreements = {}
        self.seasons = {}
        self.writers = {}
        self.windows = {}
        self.rooms = {}
        self.seats = {}
        self.episodes = {}
        self.assignments = {}
        self.milestones = {}
        self.reviews = {}
        self.items = {}
        self.submissions = {}
        self.arbitrations = {}
        self.ledger = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Logical clock reading (PRD 2.5)."""
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(UTC)


def base_row():
    """id + created_at/updated_at/version common properties (PRD 2.4)."""
    stamp = wall_now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def append_row():
    """Append-only row: id + created_at only (FeeLedgerEntry)."""
    return {"id": new_id(), "created_at": wall_now(), "_seq": db.next_seq()}


def touch(row):
    """Refresh updated_at and bump version for a mutated row (PRD 2.4)."""
    row["updated_at"] = wall_now()
    row["version"] = row.get("version", 1) + 1
    return row


def created_order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def day_floor(dt):
    return datetime(dt.year, dt.month, dt.day, tzinfo=UTC)


def end_of_day(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=UTC)
