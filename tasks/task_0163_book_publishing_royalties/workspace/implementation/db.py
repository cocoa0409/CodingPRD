"""In-memory data store. Starts empty on every boot — NO seeding.

All state lives in module-level dicts keyed by UUID id. A fresh process
(start.sh re-invocation) wipes every byte of state.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
authors = {}
agents = {}
contracts = {}
titles = {}
formats = {}
royalty_tiers = {}
sales_periods = {}
sales_records = {}
returns_reserves = {}
subsidiary_rights = {}
author_statements = {}
statement_lines = {}

_lock = threading.RLock()

# Monotonic creation counter to provide a stable secondary sort key when two
# resources share an identical millisecond timestamp. created_at remains the
# primary documented sort key (PRD §2.3); _seq breaks ties deterministically.
_seq_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq_counter)


def make_common(extra=None):
    """System-managed common fields: id, created_at, updated_at, version."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def make_light(extra=None):
    """Immutable light entities (RoyaltyTier, StatementLine): only id + created_at."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutated common-fields resource."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
