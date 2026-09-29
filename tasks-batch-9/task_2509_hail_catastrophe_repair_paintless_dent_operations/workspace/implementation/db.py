"""In-memory data store.

The store starts EMPTY on every boot. No entity is ever seeded, preloaded or
hardcoded: every row is created by a client through the declared endpoints.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

from clock import format_audit_instant

# PRD §2.4 pins the *logical* clock to "every date, expiry, window and interval
# rule" and lists the instant-typed fields it stamps; `created_at`/`updated_at`
# are not on that list.  They record "when the row was first written" (PRD §2.5)
# with three fractional digits, and PRD §3.5/§3.7 break ties "by `created_at`
# ascending", so the audit stamp has to advance between two rows written inside
# the same logical instant.
_audit_lock = threading.Lock()
_last_audit = None


def _audit_now():
    """A strictly increasing wall-clock stamp, so created_at is a total order."""
    global _last_audit
    with _audit_lock:
        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        if _last_audit is not None and now <= _last_audit:
            now = _last_audit + timedelta(milliseconds=1)
        _last_audit = now
        return format_audit_instant(now)


class Store:
    COLLECTIONS = (
        "storm_events",
        "facilities",
        "permits",
        "technicians",
        "housing_units",
        "crew_deployments",
        "insurers",
        "rate_agreements",
        "vehicles",
        "damage_lines",
        "work_tickets",
        "supplements",
        "quality_inspections",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    """Common system fields (PRD §2.5)."""
    row = {
        "id": new_id(),
        "created_at": _audit_now(),
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by one."""
    row["updated_at"] = _audit_now()
    row["version"] = row.get("version", 1) + 1
    return row


def sorted_rows(rows):
    """Every list endpoint returns rows sorted by created_at ascending (PRD §2.3).

    `_seq` is the monotone insertion counter; it only breaks ties between rows
    written at the same logical instant, preserving insertion order.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def newest_first(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
