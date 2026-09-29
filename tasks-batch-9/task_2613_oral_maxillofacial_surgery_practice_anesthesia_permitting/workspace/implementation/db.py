"""In-memory store.

Every collection starts empty on boot: no seeding, no preloading, no fixtures.
Rows are plain dicts; keys beginning with '_' are internal and never serialised.
"""
import threading
import uuid

from timeutil import fmt_dt, parse_dt

# PRD 2.5: the logical clock starts at this instant on a cold boot.
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.current_utc = CLOCK_DEFAULT
        self._seq = 0
        self.practices = {}
        self.permits = {}
        self.inspections = {}
        self.drills = {}
        self.staff = {}
        self.patients = {}
        self.blocks = {}
        self.cases = {}
        self.evaluations = {}
        self.determinations = {}
        self.lots = {}
        self.reservations = {}
        self.events = {}
        self.studies = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def clock_str():
    return db.current_utc


def clock_dt():
    return parse_dt(db.current_utc)


def set_clock(dt):
    db.current_utc = fmt_dt(dt)


def new_record(fields, immutable=False):
    """Stamp the common fields (PRD 2.4) onto a freshly built row."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = db.current_utc
    if not immutable:
        rec["updated_at"] = db.current_utc
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4)."""
    rec["updated_at"] = db.current_utc
    rec["version"] = int(rec.get("version", 1)) + 1
    return rec


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(rows):
    """Ascending created_at, with insertion sequence as the deterministic tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
