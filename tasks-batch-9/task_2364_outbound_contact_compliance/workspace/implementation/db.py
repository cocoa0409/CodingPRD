"""In-memory data store and the logical clock (PRD §2.5).

The store always starts empty: no entity is ever seeded, preloaded or
hardcoded at import or startup time.
"""

import itertools
import uuid
from datetime import datetime

from util import UTC, iso

# Before any client has set the clock it reads exactly 2026-08-01T00:00:00Z and
# never falls back to real wall-clock time (PRD §2.5).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "contacts",
    "consent_records",
    "revocation_requests",
    "suppression_entries",
    "scrub_jobs",
    "campaigns",
    "dialer_profiles",
    "agent_scripts",
    "calling_window_policies",
    "contact_attempts",
    "complaints",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # Synthetic reassigned-number lookup table (phone_number -> date str).
        self.rnd_records = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The current logical clock instant."""
    return db.clock


def now_iso():
    return iso(db.clock)


def new_id():
    return str(uuid.uuid4())


def base_row():
    """The four system-managed properties every resource family carries."""
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Register a mutation of a row: refresh updated_at, bump version."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_created_at(rows):
    """Default list ordering: created_at ascending (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
