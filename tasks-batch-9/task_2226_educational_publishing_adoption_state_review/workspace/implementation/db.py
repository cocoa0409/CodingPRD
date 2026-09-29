"""In-memory data store, id/sequence generation, and the logical adoption clock.

The store starts completely empty on every boot.  Nothing is seeded here.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.5 - before any client sets it, the logical clock reads exactly this instant.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.state_profiles = {}
        self.state_standards = {}
        self.adoption_cycles = {}
        self.titles = {}
        self.ancillary_bundles = {}
        self.content_edits = {}
        self.submissions = {}
        self.correlation_entries = {}
        self.committee_panels = {}
        self.presentation_slots = {}
        self.committee_votes = {}
        self.public_comments = {}
        self.pricing_proposals = {}
        self.district_orders = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_record(with_version=True):
    """Common fields per PRD 2.4."""
    stamp = now()
    rec = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version (PRD 2.4)."""
    if "updated_at" in rec:
        rec["updated_at"] = now()
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def apply_changes(rec, changes):
    """Write changes; refresh updated_at / bump version only when something moved."""
    dirty = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            dirty = True
    if dirty:
        touch(rec)
    return dirty


def ordered(values):
    """Records sorted by created_at ascending (insertion sequence breaks ties)."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
