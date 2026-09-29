"""In-memory state. No database, no file, no seeded data.

Everything lives in plain dicts keyed by id. A fresh process therefore starts
completely empty with the logical clock at 2026-08-01T00:00:00Z, which is what
the per-test-server harness relies on.
"""
import uuid
from datetime import datetime

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_EPOCH
        self._seq = 0
        self.practices = {}
        self.patients = {}
        self.nurses = {}
        self.licenses = {}
        self.shifts = {}
        self.coverage_windows = {}
        self.protocols = {}
        self.calls = {}
        self.assessments = {}
        self.dispositions = {}
        self.warm_transfers = {}
        self.callback_tasks = {}
        self.audit_records = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    """Common resource properties: id, created_at and (usually) updated_at/version."""
    now = store.clock
    record = {"id": new_id(), "created_at": now, "_seq": store.next_seq()}
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version — but at most ONCE per request.

    A single request often writes the same row through several code paths (a
    cascade that clears a flag on the call the request is also advancing, a
    counter helper called twice on one nurse). The specification always says
    "increments version by 1" for the whole request, so the bump is deduplicated
    per request rather than per assignment.
    """
    record["updated_at"] = store.clock
    if "version" not in record:
        return record
    touched = _touched_set()
    if touched is None:
        record["version"] = int(record["version"]) + 1
        return record
    if record["id"] in touched:
        return record
    touched.add(record["id"])
    record["version"] = int(record["version"]) + 1
    return record


def _touched_set():
    """The set of row ids already version-bumped by the request in flight."""
    try:
        from flask import g, has_request_context
    except ImportError:                                   # pragma: no cover
        return None
    if not has_request_context():
        return None
    touched = getattr(g, "_touched_ids", None)
    if touched is None:
        touched = set()
        g._touched_ids = touched
    return touched


def ordered(collection):
    """List rows oldest-first: created_at ascending, insertion order as tiebreak."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
