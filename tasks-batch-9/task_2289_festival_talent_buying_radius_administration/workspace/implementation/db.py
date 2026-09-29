"""In-memory store. The store is EMPTY on every boot: nothing is ever seeded."""

import uuid
from datetime import datetime, timezone

# PRD 2.5 - the logical clock reads this instant until a client sets it.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "festivals",
    "budget_tiers",
    "stages",
    "artists",
    "offers",
    "radius_clauses",
    "competing_performances",
    "bookings",
    "rider_items",
    "advance_packets",
    "payment_installments",
    "announcement_waves",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def wall_now():
    return datetime.now(timezone.utc)


def iso_instant(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def clock_now():
    return db.clock


def new_row(**fields):
    ts = iso_instant(wall_now())
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """PRD 2.4 - any write that changes a row bumps version and updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso_instant(wall_now())
    return row


def freshen(row):
    """Collapse intra-request derivations on a brand new row back to version 1."""
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return row


def apply_changes(row, changes):
    """Assign only the keys that actually move; report whether anything moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
