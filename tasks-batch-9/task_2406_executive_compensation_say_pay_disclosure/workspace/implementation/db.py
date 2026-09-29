"""In-memory data store, logical clock and row bookkeeping.

Storage is process-local dictionaries keyed by id.  Nothing is persisted and
nothing is ever seeded: every boot starts with an empty store (PRD §2.4 — the
logical clock cold-starts at 2026-08-01T00:00:00Z).
"""

import uuid
from datetime import datetime, timezone

from flask import g

# PRD §2.4: the server starts cold at this fixed instant and never falls back to
# the host clock.
COLD_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLE_NAMES = (
    "companies",
    "executives",
    "peer_groups",
    "peer_group_members",
    "pay_programs",
    "incentive_metrics",
    "payout_awards",
    "cda_drafts",
    "proxy_advisor_screens",
    "outreach_engagements",
    "restatement_events",
    "clawback_determinations",
)


class Store:
    def __init__(self):
        for name in TABLE_NAMES:
            setattr(self, name, {})
        self.current_utc = COLD_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    return store.current_utc


def set_now(instant):
    store.current_utc = instant


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        instant.second,
        instant.microsecond // 1000,
    )


def sec(instant):
    """Instant comparisons are made at second granularity (PRD §2.5)."""
    return None if instant is None else instant.replace(microsecond=0)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def insert(table, fields):
    row = {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(fields)
    table[row["id"]] = row
    return row


def _touched_set():
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def touch(row):
    """Register a mutation: version += 1 (once per request) and updated_at."""
    seen = _touched_set()
    row["updated_at"] = now()
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["version"] += 1


def apply_changes(row, changes):
    """Write only the fields that actually move; touch the row when any did."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def ordered(rows):
    """Default list ordering: creation timestamp ascending (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def children(table, field, value):
    return ordered([r for r in table.values() if r.get(field) == value])
