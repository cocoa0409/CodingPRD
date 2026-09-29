"""In-memory store. Process-local dicts only; nothing is persisted and nothing
is ever seeded — every row in here is created by an API call."""

import itertools
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

TABLES = (
    "facilities",
    "templates",
    "contracts",
    "shifts",
    "forecasts",
    "encounters",
    "ancillary_orders",
    "agreements",
    "mous",
    "transfer_orders",
    "claims",
    "disputes",
    "ledger",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for table in TABLES:
            setattr(self, table, {})
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    @property
    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row():
    now = db.clock
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Every mutation of a row refreshes updated_at and bumps version by 1."""
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 0) + 1


def row_key(row):
    """created_at ASC with a monotonic tiebreak (the logical clock can tie)."""
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=row_key)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)
