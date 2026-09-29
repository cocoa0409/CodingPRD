"""In-memory store. Starts EMPTY on every boot — nothing is ever seeded."""

import itertools
import uuid

from util import DEFAULT_CLOCK_ISO, parse_dt


class DB:
    def __init__(self):
        # PRD §2.5 — the logical clock; never wall-clock time.
        self.clock_iso = DEFAULT_CLOCK_ISO
        self._counter = itertools.count(1)
        self.cycles = {}
        self.scenarios = {}
        self.sources = {}
        self.adjustments = {}
        self.items = {}
        self.rounds = {}
        self.estimates = {}
        self.disagreements = {}
        self.funds = {}
        self.transactions = {}
        self.requests = {}
        self.votes = {}
        self.actuals = {}
        self.briefings = {}


db = DB()


def now_iso():
    return db.clock_iso


def now_dt():
    return parse_dt(db.clock_iso)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._counter)


def make_record(fields, versioned=True):
    """Common fields of PRD §2.6: id, created_at, and (usually) updated_at/version."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = now_iso()
    if versioned:
        rec["updated_at"] = now_iso()
        rec["version"] = 1
    rec["_seq"] = next_seq()
    rec["_ct"] = parse_dt(rec["created_at"])
    return rec


def touch(rec):
    """A mutation: refresh updated_at and bump version (PRD §2.6)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def _sort_key(rec):
    return (rec["_ct"], rec["_seq"])


def ordered(records):
    """Default list ordering: created_at ascending (PRD §2.3), stable by mint order."""
    if isinstance(records, dict):
        records = records.values()
    return sorted(records, key=_sort_key)


def store_for(name):
    return getattr(db, name)
