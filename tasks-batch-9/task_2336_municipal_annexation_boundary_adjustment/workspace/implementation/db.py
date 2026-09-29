"""In-memory data store (PRD §2.4, §2.5).

Every collection is a plain dict keyed by the record's UUID `id`. The store starts
completely empty on every boot: nothing is seeded, preloaded or hardcoded here.
The logical clock starts at exactly 2026-08-01T00:00:00Z.
"""

import threading
import uuid
from datetime import datetime

from clockutil import UTC

CLOCK_STARTUP = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "statute_profiles",
    "municipalities",
    "service_providers",
    "property_owners",
    "cases",
    "parcels",
    "petitions",
    "consents",
    "analyses",
    "plans",
    "commitments",
    "hearings",
    "notices",
    "filings",
    "utility_accounts",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_STARTUP
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The logical clock — never the host's real time."""
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record():
    """id + the common system fields of PRD §2.5."""
    stamp = db.now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def notice_record():
    """NoticePublication carries only `id` and `created_at` (PRD §2.5)."""
    return {"id": new_id(), "created_at": db.now(), "_seq": db.next_seq()}


def touch(record):
    """A full mutation: refresh updated_at and increment version."""
    record["updated_at"] = db.now()
    record["version"] = record.get("version", 1) + 1


def ordered(records):
    """created_at ascending, with a stable insertion tiebreak."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
