"""In-memory data store and server-controlled logical clock.

The store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded here or anywhere else at startup.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.7 — the logical clock starts at exactly this instant on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "plans",
    "strategies",
    "participants",
    "audits",
    "windows",
    "elections",
    "tranches",
    "insurers",
    "quotes",
    "experts",
    "transfers",
    "entries",
    "complaints",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_START
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    return db.clock


def set_clock(value):
    db.clock = value


def iso(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def parse_datetime(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                value = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def days(count):
    return timedelta(days=count)


def new_id():
    return str(uuid.uuid4())


def make_entity(versioned=True):
    """Common fields (PRD 2.6): server UUID id, created_at, updated_at, version."""
    stamp = now()
    record = {"id": new_id(), "created_at": stamp}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """A mutation (including a derived recomputation) moves updated_at and bumps version."""
    record["updated_at"] = now()
    record["version"] = record.get("version", 1) + 1
    return record


def public(record):
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = iso(value) if isinstance(value, datetime) else value
    return out


def ordered(records):
    """Default list order: created_at ascending (stable by insertion sequence)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
