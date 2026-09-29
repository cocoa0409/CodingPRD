"""In-memory store. Starts completely empty on every boot: nothing is seeded."""
import itertools
import threading
import uuid

import clock

LOCK = threading.RLock()

code_cycles = {}
discipline_committees = {}
committee_members = {}
amendment_proposals = {}
impact_analyses = {}
public_comments = {}
hearings = {}
vote_records = {}
adoption_rules = {}
jurisdictions = {}
local_amendments = {}
interpretation_requests = {}
training_sessions = {}
training_enrollments = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_record(fields, versioned=True):
    """Build a record with the system fields described in PRD 2.4."""
    record = {"id": new_id(), "created_at": clock.now()}
    record.update(fields)
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version — one server-side mutation."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
    return record


def ordered(rows):
    """Default sort: created_at ascending, insertion order as stable tie break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
