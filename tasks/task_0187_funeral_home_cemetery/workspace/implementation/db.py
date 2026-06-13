"""In-memory data store. Starts EMPTY on every boot; no seeding.

Each entity collection is a dict keyed by id (server-minted UUID, no prefix).
A monotonic counter provides a stable insertion sequence used for deterministic
created_at tie-breaks and posted_at chronological replay.
"""
import threading
import uuid

from clock import now_iso, now_dt

_lock = threading.RLock()
_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


# Collections keyed by id
funeral_homes = {}
gpl_items = {}
cases = {}
statement_lines = {}
contracts = {}
trust_deposits = {}
insurance_assignments = {}
plots = {}
venues = {}
events = {}
permits = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Populate common system fields on a freshly created record."""
    ts = now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = _next_seq()
    return record


def touch(record):
    """Bump version and refresh updated_at on mutation (including cascades)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def lock():
    return _lock
