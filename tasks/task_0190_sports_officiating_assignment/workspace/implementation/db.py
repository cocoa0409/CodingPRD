"""In-memory data store.

All state lives in module-level dicts keyed by id. Nothing is seeded at
import time — every entity is created by a test through the declared API
surface. A fresh process (start.sh re-invocation) gives a clean store.

Common system fields (PRD §2.4):
  - id           : UUID v4 string, no type prefix
  - created_at   : ISO 8601 UTC, three fractional digits, set at creation
  - updated_at   : refreshed on every mutation (absent on ConflictDeclaration/Evaluation)
  - version      : starts at 1, +1 per mutation (absent on ConflictDeclaration/Evaluation)

A global monotonically increasing sequence is stamped on every record at
creation so list endpoints can sort by created_at ascending with a stable
tiebreak even when several records share the same millisecond.
"""
import threading
import uuid
from datetime import datetime, timezone

from timeutil import iso_now_ms

# Collections keyed by id.
leagues = {}
officials = {}
games = {}
crew_slots = {}
assignments = {}
availabilities = {}
conflict_declarations = {}
evaluations = {}
season_ledgers = {}
penalty_appeals = {}

lock = threading.RLock()

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def stamp_create(record, common_fields=True):
    """Populate id + creation system fields on a new record (in place)."""
    record["id"] = new_id()
    now_dt = datetime.now(timezone.utc)
    record["created_at"] = iso_now_ms(now_dt)
    record["_seq"] = _next_seq()
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at + bump version on a mutation (PRD §2.4)."""
    record["updated_at"] = iso_now_ms(datetime.now(timezone.utc))
    record["version"] = record.get("version", 0) + 1
    return record
