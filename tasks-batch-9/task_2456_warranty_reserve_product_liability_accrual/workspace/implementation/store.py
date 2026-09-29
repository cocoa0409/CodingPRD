"""In-memory data store and the logical UTC clock (PRD §2.4, §2.5).

The store starts completely empty on every boot.  Nothing is ever seeded,
preloaded or hardcoded: every row is created through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

from response import format_instant

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Collections — one dict per entity kind, keyed by id.
# ---------------------------------------------------------------------------
COLLECTIONS = (
    "periods",
    "families",
    "vintages",
    "failure_modes",
    "observations",
    "accruals",
    "adequacy_reviews",
    "field_actions",
    "remedy_options",
    "service_contracts",
    "suppliers",
    "recoveries",
    "liability_reserves",
    "rollforwards",
)

_data = {name: {} for name in COLLECTIONS}
_seq = itertools.count(1)

# The logical clock, before any client has set it, reads exactly this instant and
# must never fall back to real wall-clock time.
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = LOGICAL_CLOCK_EPOCH

_last_wall = None


def reset():
    """Empty every collection and reset the logical clock (fresh-process boot)."""
    global _logical_now, _seq
    for name in COLLECTIONS:
        _data[name].clear()
    _seq = itertools.count(1)
    _logical_now = LOGICAL_CLOCK_EPOCH


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def logical_now():
    return _logical_now


def logical_now_iso():
    return format_instant(_logical_now)


def logical_date():
    return _logical_now.date()


def set_logical_now(dt):
    global _logical_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _logical_now = dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Row identity / timestamps
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _wall_now():
    """Strictly increasing wall-clock instant so created_at order == insert order."""
    global _last_wall
    now = datetime.now(timezone.utc)
    if _last_wall is not None and now <= _last_wall:
        now = _last_wall + timedelta(microseconds=1000)
    _last_wall = now
    return now


def now_iso():
    return format_instant(_wall_now())


def insert(collection, row, common_fields=True):
    """Insert a freshly minted row.  ``row`` must already carry its own fields."""
    row["id"] = new_id()
    row["created_at"] = now_iso()
    if common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next(_seq)
    _data[collection][row["id"]] = row
    return row


def touch(row):
    """Register a real mutation: refresh updated_at and bump version by one."""
    row["updated_at"] = now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return _data[collection].get(row_id)


def all_rows(collection):
    """Every row of the collection in created_at ascending order."""
    return sorted(_data[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def count(collection):
    return len(_data[collection])
