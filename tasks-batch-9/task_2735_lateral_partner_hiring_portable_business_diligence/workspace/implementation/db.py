"""In-memory data store.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded: every entity is created by callers through the declared endpoints.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from response import iso3

# Logical clock default (PRD section 2.4).
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "practice_groups",
    "search_firms",
    "engagements",
    "candidates",
    "questionnaires",
    "client_book_entries",
    "collection_records",
    "assessments",
    "conflict_checks",
    "waivers",
    "declinations",
    "offers",
    "votes",
    "integration_plans",
    "introductions",
    "performance_reviews",
)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def new_row(fields, versioned=True):
    """Create a row with the common system fields (PRD section 2.4)."""
    row = {"id": str(uuid.uuid4()), "created_at": db.now()}
    if versioned:
        row["updated_at"] = db.now()
        row["version"] = 1
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and bump version by one (a single mutation)."""
    row["updated_at"] = db.now()
    row["version"] = row.get("version", 1) + 1
    return row


def set_fields(row, **fields):
    """Write fields; bump version once if at least one value actually changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def order_key(row):
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=order_key)


def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _convert(v)) for k, v in value.items())
    return value


def pub(row):
    """Public representation: drop internal keys, convert Decimal/datetime."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _convert(value)
    return out


def pub_list(rows):
    return [pub(r) for r in rows]


def values(collection):
    return list(getattr(db, collection).values())
