"""In-memory data store.  Starts completely empty on every boot: no seeding."""
import itertools
import threading
import uuid

from clock import now_iso

COLLECTIONS = (
    "race_editions",
    "purse_lines",
    "division_standards",
    "athletes",
    "rep_agents",
    "performance_records",
    "invitations",
    "negotiation_rounds",
    "pacer_assignments",
    "fluid_station_slots",
    "doping_tests",
    "race_results",
    "prize_awards",
)


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self._counter = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._counter)


db = DB()


def new_id():
    return str(uuid.uuid4())


def new_record(with_version=True, **fields):
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD 2.5)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def order_key(rec):
    """created_at ascending, with the insertion sequence as a stable tie-break."""
    return (rec["created_at"], rec["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def all_rows(collection):
    return sorted_rows(getattr(db, collection).values())
