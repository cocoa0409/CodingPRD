"""In-memory data store.  Dicts keyed by id; nothing is ever seeded."""
import uuid

import clock

COLLECTIONS = (
    "pollutants",
    "reference_methods",
    "networks",
    "sites",
    "monitors",
    "qc_events",
    "data_batches",
    "invalidations",
    "demonstrations",
    "exclusions",
    "design_values",
    "assessments",
    "change_requests",
    "packages",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(common_fields=True):
    """Fresh record skeleton.  created_at/updated_at come from the logical clock."""
    rec = {"id": new_id(), "created_at": clock.now(), "_seq": store.next_seq()}
    if common_fields:
        rec["updated_at"] = clock.now()
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = clock.now()
    return rec


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
