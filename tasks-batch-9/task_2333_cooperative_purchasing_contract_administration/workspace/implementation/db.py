"""In-memory data store, identity/timestamp helpers and the logical clock.

Storage is process-local Python dictionaries only.  The store is EMPTY on every
boot: no entity is seeded, preloaded or hardcoded at startup.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: the logical clock starts at this instant on every boot and is only
# ever moved by POST /_clock/set_current_utc.  There is no wall-clock fallback.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """Collections of rows keyed by uuid string.  Insertion order == creation order."""

    def __init__(self):
        self.state_law_rules = {}
        self.solicitations = {}
        self.suppliers = {}
        self.responses = {}
        self.contracts = {}
        self.line_items = {}
        self.members = {}
        self.analyses = {}
        self.usages = {}
        self.reports = {}
        self.amendments = {}
        self.complaints = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def utc_now():
    return datetime.now(timezone.utc)


def logical_now():
    """The logical clock instant (PRD 2.4)."""
    return db.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def real_now_iso():
    return iso(utc_now())


def logical_now_iso():
    """PRD 2.4: row timestamps read the logical clock, never system time."""
    return iso(logical_now())


def parse_dt(value):
    """Parse an ISO 8601 datetime string; return None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def months_between(start, end):
    """Whole calendar months from start to end with day-of-month correction.

    PRD: (end.year - start.year) * 12 + (end.month - start.month), minus one
    when end's day-of-month is earlier than start's.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def create_row(collection, versioned=True, **fields):
    """Build and register a row.

    Public key order is id, then the entity's declared fields in the order
    given, then created_at (and updated_at / version for mutable entities).
    Datetime-valued fields must be listed in ``fields`` so that a later
    :func:`set_dt` preserves their position.
    """
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = logical_now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_dt"] = {}
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    return row


def set_dt(row, field, value):
    """Store a datetime-valued field.

    A client-supplied string is echoed back verbatim; a server-computed
    datetime is rendered with three fractional digits.  The parsed value is
    kept in the row's private ``_dt`` side-table for arithmetic.
    """
    store = row.setdefault("_dt", {})
    if value is None:
        row[field] = None
        store[field] = None
    elif isinstance(value, datetime):
        row[field] = iso(value)
        store[field] = value.astimezone(timezone.utc)
    else:
        row[field] = value
        store[field] = parse_dt(value)


def get_dt(row, field):
    return row.get("_dt", {}).get(field)


def serialize(row):
    """Public representation: every non-private key, in declaration order."""
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def sort_key(row):
    """Default list ordering: created_at ascending, stable by creation sequence."""
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(collection):
    return sorted(collection.values(), key=sort_key)
