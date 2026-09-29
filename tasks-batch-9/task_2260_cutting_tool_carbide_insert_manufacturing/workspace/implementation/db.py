"""In-memory data store.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here: every row is created through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

from response import iso_now

# ---------------------------------------------------------------- collections
grades = {}
batches = {}
geometries = {}
recipes = {}
coating_runs = {}
wheels = {}
grinding_runs = {}
products = {}
dossiers = {}
trials = {}
customers = {}
orders = {}
jobs = {}

lock = threading.RLock()

_seq = itertools.count(1)

# ---------------------------------------------------------------- logical clock
CLOCK_DEFAULT_TEXT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

clock = {"text": CLOCK_DEFAULT_TEXT, "dt": CLOCK_DEFAULT_DT}


def now_dt():
    """The current logical UTC instant."""
    return clock["dt"]


def now_text():
    return clock["text"]


def set_clock(text, dt):
    clock["text"] = text
    clock["dt"] = dt


def logical_iso():
    """Logical clock rendered in the common ISO-8601 millisecond form."""
    dt = clock["dt"].astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------- row helpers
def new_row(fields):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": iso_now(),
        "updated_at": None,
        "version": 1,
    }
    row["updated_at"] = row["created_at"]
    row.update(fields)
    row["_seq"] = next(_seq)
    return row


def touch(row):
    row["version"] = row["version"] + 1
    row["updated_at"] = iso_now()


def ordered(rows):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
