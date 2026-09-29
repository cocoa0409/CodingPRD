"""In-memory data store, id/timestamp helpers and the logical clock.

Storage is process-local and starts completely empty on every boot: no
seeding, no preloading, no persistence of any kind.
"""

import uuid
from datetime import datetime, timezone

CLOCK_STARTUP_RAW = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "programs",
    "plants",
    "binders",
    "product_lines",
    "runs",
    "changeovers",
    "thermal_tests",
    "lots",
    "cullet",
    "cycles",
    "orders",
    "lines",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock_raw = CLOCK_STARTUP_RAW
        self.clock_dt = CLOCK_STARTUP_DT

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def real_now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def clock_now():
    return store.clock_dt


def clock_raw():
    return store.clock_raw


def clock_iso():
    return fmt_ts(store.clock_dt)


def new_id():
    return str(uuid.uuid4())


def new_row(common=True):
    """Fresh row skeleton: bare uuid id, created_at, and (usually) the
    updated_at / version pair.  ``_seq`` keeps insertion order stable when two
    rows share a created_at millisecond."""
    stamp = fmt_ts(real_now())
    row = {"id": new_id(), "created_at": stamp}
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    row["updated_at"] = fmt_ts(real_now())
    if "version" in row:
        row["version"] = row["version"] + 1


def ordered(rows):
    """Default ordering for every list endpoint: created_at ascending, with
    insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
