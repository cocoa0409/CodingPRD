"""In-memory data store. Starts empty on every boot."""
import itertools
import uuid

import clock

# One dict per entity type, keyed by id.
clients = {}
opportunities = {}
engagements = {}
matches = {}
proposals = {}
budget_lines = {}
deliverables = {}
revision_requests = {}
submissions = {}
time_entries = {}
invoices = {}
awards = {}
compliance_reports = {}
boilerplate = {}

# Monotonic sequence for stable creation ordering (created_at can collide
# because the logical clock does not advance on its own).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def init_common(rec):
    """Populate server-minted common fields on a new resource."""
    now = clock.now_iso()
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Bump version + updated_at on mutation."""
    rec["version"] += 1
    rec["updated_at"] = clock.now_iso()
