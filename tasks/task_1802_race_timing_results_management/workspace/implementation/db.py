"""In-memory data store. Empty on every boot; no seeding, no persistence."""
import itertools
import threading
import uuid

import clock
from util import fmt_dt

lock = threading.RLock()
_seq = itertools.count(1)

races = {}
waves = {}
timing_points = {}
registrations = {}
chips = {}
timing_reads = {}
results = {}
result_flags = {}
protests = {}
corrections = {}
certifications = {}
awards = {}


def next_seq():
    return next(_seq)


def new_entity():
    """Common system-managed fields for a fresh primary resource."""
    ts = fmt_dt(clock.now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Stamp a modification: refresh updated_at, increment version."""
    entity["updated_at"] = fmt_dt(clock.now())
    entity["version"] = entity.get("version", 1) + 1
