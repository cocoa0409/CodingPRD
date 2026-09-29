"""In-memory storage, logical clock and row helpers.

Storage is process-local Python dictionaries only.  Nothing is persisted to
disk and no entity data is seeded at startup.
"""

import itertools
import random
import string
import uuid
from datetime import date, datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "packages",
    "submittals",
    "releases",
    "glass_orders",
    "draws",
    "lots",
    "labs",
    "mockups",
    "surveys",
    "zones",
    "crew_days",
    "rigs",
    "reservations",
    "field_tests",
    "defects",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# clock / formatting
# --------------------------------------------------------------------------
def now():
    return db.clock


def fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(db.clock)


def parse_dt(raw):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(raw):
    """Strict YYYY-MM-DD parse, returning a date or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def as_date(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    return parse_date(value)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_row(versioned=True):
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso()


def apply(row, updates):
    """Assign updates; bump version/updated_at once if anything really changed."""
    changed = False
    for key, value in updates.items():
        if key not in row or row[key] != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def collection(mapping, **filters):
    """All rows of a mapping matching every non-None filter, chronologically."""
    out = []
    for row in mapping.values():
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return sort_rows(out)
