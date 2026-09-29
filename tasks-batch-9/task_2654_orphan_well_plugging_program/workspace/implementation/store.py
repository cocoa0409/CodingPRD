"""In-memory data store, logical regulatory clock, and row helpers.

Storage is process-local Python dicts keyed by id. Nothing is persisted to disk
and NO entity data is ever seeded at import time or at startup: every row is
created through the declared API surface.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

UTC = timezone.utc

# Section 2.5 - before any client sets it the logical clock reads exactly this.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.operators = {}
        self.wells = {}
        self.production_records = {}
        self.determinations = {}
        self.site_accesses = {}
        self.transfers = {}
        self.contractors = {}
        self.solicitations = {}
        self.bids = {}
        self.contracts = {}
        self.jobs = {}
        self.tasks = {}
        self.funding_sources = {}
        self.allocations = {}
        self.grant_reports = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    db.seq += 1
    return db.seq


def clock():
    return db.clock


def set_clock(dt):
    db.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (section 2.4)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO-8601 instant. Raises ValueError when malformed."""
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def days(n):
    return timedelta(days=n)


def new_row(common=True):
    """Fresh row skeleton. created_at is read from the logical clock."""
    row = {"id": new_id(), "created_at": clock(), "_seq": next_seq()}
    if common:
        row["updated_at"] = clock()
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = clock()
    row["version"] = row.get("version", 0) + 1
    return row


def _conv(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_conv(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _conv(v)) for k, v in value.items())
    return value


def serialize(row):
    """Public representation: private keys (leading underscore) are dropped."""
    if row is None:
        return None
    return dict((k, _conv(v)) for k, v in row.items() if not k.startswith("_"))


def serialize_many(rows):
    return [serialize(r) for r in rows]


def sort_rows(rows, key=None):
    """Stable ordering; the insertion sequence is the final tiebreak so that
    rows sharing a logical-clock created_at keep their filing order."""
    if key is None:
        return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    return sorted(rows, key=lambda r: (key(r), r["_seq"]))
