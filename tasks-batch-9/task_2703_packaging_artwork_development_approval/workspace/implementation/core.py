"""In-memory store, logical clock, timestamp rendering and version/touch discipline.

PRD 2.4: every persisted row carries a UUID `id` with no type prefix, `created_at`,
`updated_at` and an integer `version` starting at 1; every mutation increments
`version` by exactly 1 and refreshes `updated_at`.

PRD 2.4: the service does not read wall-clock time for business decisions; all
`*_at` / `*_utc` values read a logical clock that starts at 2026-08-01T00:00:00Z.
"""
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "briefs",
    "claims",
    "assets",
    "versions",
    "element_checks",
    "routes",
    "tasks",
    "printers",
    "proofs",
    "plate_orders",
    "runouts",
    "escapes",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------- timestamps
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
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


def parse_dt(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    """The current logical-clock instant."""
    return db.clock


def now_iso():
    return fmt_dt(db.clock)


def wall_iso():
    return fmt_dt(datetime.now(timezone.utc))


def date_str(dt):
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------- rounding
def round_half_up(value, places):
    """Decimal ROUND_HALF_UP to `places` decimal places (PRD 2.8)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_int(value):
    return int(dec(value))


def to_float(value):
    return float(value)


# ---------------------------------------------------------------- row lifecycle
def _touched():
    marks = getattr(g, "_touched_rows", None)
    if marks is None:
        marks = set()
        g._touched_rows = marks
    return marks


def new_row(collection, fields):
    """Create a row with the common audit fields. Version starts at 1."""
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row["id"]] = row
    # A row created inside this request is already at its post-request version.
    _touched().add(id(row))
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1, at most once per request."""
    if row is None:
        return row
    marks = _touched()
    key = id(row)
    if key in marks:
        return row
    marks.add(key)
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


def rows(collection):
    return list(getattr(db, collection).values())


def by_seq(items):
    return sorted(items, key=lambda r: r["_seq"])
