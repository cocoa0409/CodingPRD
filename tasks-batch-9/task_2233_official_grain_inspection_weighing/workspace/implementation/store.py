"""In-memory store, the logical clock and record helpers.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is ever pre-seeded: every row is created by an API caller.
"""

import itertools
import uuid
from datetime import datetime, timezone, timedelta

# PRD §2.5 — the logical clock starts here on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "service_areas",
    "fee_schedules",
    "applicants",
    "inspectors",
    "equipment",
    "inspection_requests",
    "samples",
    "grading_results",
    "protein_analyses",
    "weighing_records",
    "certificates",
    "appeals",
    "appeal_votes",
    "vessel_watches",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.now = CLOCK_START
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # An ISO 8601 UTC instant: date, the 'T' designator, time, and an explicit
    # zone designator.  Anything looser (a space separator, a missing zone) is
    # not an instant and is rejected by the schema rung.
    if "T" not in text and "t" not in text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def now():
    return db.now


def days(count):
    return timedelta(days=count)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_row(fields, common_fields=True):
    """Create a row with the common record properties of PRD §2.4."""
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = db.now
    if common_fields:
        row["updated_at"] = db.now
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Register a mutation: refresh updated_at and bump version."""
    if "version" in row:
        row["updated_at"] = db.now
        row["version"] = row["version"] + 1
    return row


def order_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _plain(value)
    return out


def _plain(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value
