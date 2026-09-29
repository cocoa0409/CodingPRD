"""In-memory data store.  The store starts EMPTY on every boot - nothing is
seeded, preloaded or hardcoded.  All state is built by callers through the
public API surface."""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.5: the logical clock reads exactly this instant when the server starts.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "brands",
    "registrations",
    "enrollments",
    "representatives",
    "sellers",
    "listings",
    "claims",
    "test_buys",
    "packages",
    "takedowns",
    "counter_notices",
    "cases",
    "recordations",
    "investigations",
)

lock = threading.RLock()

_state = {
    "clock": CLOCK_START,
    "seq": itertools.count(1),
    "tables": {name: {} for name in TABLES},
}


def reset():
    _state["clock"] = CLOCK_START
    _state["seq"] = itertools.count(1)
    _state["tables"] = {name: {} for name in TABLES}


def now():
    """The single server-side logical UTC clock.  Never falls back to
    wall-clock time."""
    return _state["clock"]


def set_now(value):
    _state["clock"] = value
    return _state["clock"]


def table(name):
    return _state["tables"][name]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_state["seq"])


def insert(name, row):
    row["_seq"] = next_seq()
    table(name)[row["id"]] = row
    return row


def get(name, row_id):
    if not isinstance(row_id, str):
        return None
    return table(name).get(row_id)


def all_rows(name):
    """Every row of a family in the canonical order: created_at ascending,
    ties broken by persistence sequence ascending.  `id` never participates."""
    return sorted(table(name).values(), key=lambda r: (r["created_at"], r["_seq"]))


def values(name):
    return list(table(name).values())
