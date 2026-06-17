"""In-memory data store. All state lives in module-level dicts keyed by id.

A fresh process (start.sh re-invocation) wipes everything — nothing is seeded,
preloaded, or persisted to disk.
"""
import itertools
import threading
import uuid

from response import now_iso

LOCK = threading.RLock()

# One dict per entity type, keyed by id.
clients = {}
freelancers = {}
job_postings = {}
proposals = {}
contracts = {}
milestones = {}
timelogs = {}
escrow_transactions = {}
disputes = {}
payouts = {}
reviews = {}
tax_records = {}

# Monotonic counter giving every record a stable insertion order, so that
# "sort by created_at ascending" is deterministic even when timestamps collide.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def new_common(extra_version=True):
    """System-managed common fields (PRD 2.4).

    id / created_at / updated_at / version. version starts at 1 and increments
    on every mutation. _seq is an internal ordering key (not serialized).
    """
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
    }
    if extra_version:
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a versioned entity as mutated: bump updated_at and version."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1
