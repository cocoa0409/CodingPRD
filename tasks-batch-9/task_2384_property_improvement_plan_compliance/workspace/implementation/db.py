"""In-memory data store, id minting, and the server-controlled logical clock.

The store is created empty on every boot.  No entity is ever seeded, preloaded
or hardcoded here — every row is created through the declared API surface.
"""

import uuid
from datetime import datetime, timezone

# PRD section 2.5: the logical clock starts at this instant on every boot and
# never falls back to host wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "franchisees",
    "properties",
    "plans",
    "items",
    "extension_requests",
    "budgets",
    "draws",
    "phases",
    "contractors",
    "bookings",
    "inspections",
    "punch_items",
    "disputes",
    "notices",
    "ledger",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """Server-minted opaque identifier: a UUID string with no type prefix."""
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def clock_now():
    return db.clock


def fmt_clock(dt):
    """The logical clock instant as the PRD writes it (section 2.5).

    The clock "reads exactly 2026-08-01T00:00:00Z", so a whole-second instant
    carries no fractional part; a sub-second instant keeps three digits.  The
    three-fractional-digit rule of section 2.4 governs `created_at` /
    `updated_at` only, and never rewrites the clock's own value.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year,
            dt.month,
            dt.day,
            dt.hour,
            dt.minute,
            dt.second,
        )
    return fmt_ts(dt)


def clock_iso():
    return fmt_clock(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def wall_now_iso():
    return fmt_ts(datetime.now(timezone.utc))
