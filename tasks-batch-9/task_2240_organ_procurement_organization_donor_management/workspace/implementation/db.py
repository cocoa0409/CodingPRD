"""In-memory data store.

Storage is process-local Python dicts keyed by resource id. Nothing is persisted
to disk and NOTHING is seeded at import time -- the store is empty on every boot
and every entity is built by callers through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.hospital_partners = {}
        self.death_referrals = {}
        self.eligibility_screenings = {}
        self.serology_results = {}
        self.authorizations = {}
        self.nok_contacts = {}
        self.donor_cases = {}
        self.observations = {}
        self.organs = {}
        self.match_runs = {}
        self.organ_offers = {}
        self.recovery_teams = {}
        self.recovery_operations = {}
        self.transport_assets = {}
        # Logical clock (PRD 2.4). Reads exactly 2026-08-01T00:00:00Z until set.
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
lock = threading.RLock()


def clock_now():
    return db.clock


def set_clock(instant):
    db.clock = instant
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(managed=True):
    """Common fields (PRD 2.4).

    Managed aggregates carry id/created_at/updated_at/version; the three
    append-only records (SerologyResult, NextOfKinContact,
    PhysiologicObservation) carry only id/created_at.

    Every server-stamped instant, `created_at` and `updated_at` included, is
    read from the logical clock: PRD 2.4 states that all domain time is read
    from it and that it "never falls back to wall-clock time under any
    circumstance".
    """
    now = clock_now()
    rec = {"id": new_id(), "_seq": db.next_seq(), "created_at": now}
    if managed:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def ordered(records):
    """Default list ordering: created_at ascending (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def by(store, **filters):
    out = []
    for rec in store.values():
        if all(rec.get(k) == v for k, v in filters.items()):
            out.append(rec)
    return ordered(out)
