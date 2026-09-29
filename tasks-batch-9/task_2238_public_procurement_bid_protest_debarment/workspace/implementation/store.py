"""In-memory store and the logical clock (PRD §2.4).

Storage is process memory only: plain Python dicts, nothing on disk. The store
starts completely empty on every boot; no entity is ever seeded here.
"""

import itertools
import uuid
from datetime import datetime

from util import UTC

# PRD §2.4: before any call to the clock capability the logical clock reads
# exactly 2026-08-01T00:00:00Z. It never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "vendors",
    "solicitations",
    "requirements",
    "addenda",
    "questions",
    "bids",
    "reviews",
    "protests",
    "hearings",
    "record_items",
    "awards",
    "proceedings",
    "petitions",
    "screenings",
)

db = {name: {} for name in COLLECTIONS}
db["clock"] = DEFAULT_CLOCK

_counter = itertools.count(1)


def now():
    return db["clock"]


def set_clock(instant):
    db["clock"] = instant
    return instant


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_counter)


def insert(collection, row):
    db[collection][row["id"]] = row
    return row


def row(collection, fields, versioned=True):
    """Build a fresh row with the system audit fields of PRD §2.4."""
    instant = now()
    base = {"id": new_id(), "created_at": instant}
    if versioned:
        base["updated_at"] = instant
        base["version"] = 1
    base.update(fields)
    base["_seq"] = next_seq()
    return base


def values(collection):
    """All rows of a collection in insertion order."""
    return list(db[collection].values())


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db[collection].get(row_id)


def ordered(rows):
    """Default ordering of PRD §2.3: created_at ascending (stable)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
