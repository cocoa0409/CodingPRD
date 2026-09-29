"""In-memory data store, logical clock, id minting and timestamp helpers.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded --
every entity is created by API clients through the declared endpoints.
"""
import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: the logical clock begins at 2026-08-01T00:00:00Z.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_START
        self._counter = itertools.count(1)
        self.retailers = {}
        self.attribute_definitions = {}
        self.retailer_requirements = {}
        self.products = {}
        self.content_versions = {}
        self.attribute_values = {}
        self.media_assets = {}
        self.listings = {}
        self.jobs = {}
        self.rejection_errors = {}
        self.change_requests = {}
        self.deployments = {}
        self.observations = {}
        self.alerts = {}

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    """Current value of the deterministic logical clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    try:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute, second = int(m.group(4)), int(m.group(5)), int(m.group(6))
        frac = m.group(7)
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1000000))
        offset = m.group(8)
        tz = timezone.utc
        if offset and offset not in ("Z", "z"):
            sign = 1 if offset[0] == "+" else -1
            body = offset[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_row():
    """Common fields: id / created_at / updated_at / version (PRD 2.4)."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def event_row():
    """Append-only event row: only id and created_at (ShelfObservation)."""
    return {"id": new_id(), "created_at": now(), "_seq": db.next_seq()}


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def in_order(rows):
    """Ascending created_at; insertion sequence breaks ties deterministically."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
