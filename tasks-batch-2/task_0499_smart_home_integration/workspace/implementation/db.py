"""In-memory data store (PRD §2.4 common fields).

All state lives in module-level dicts keyed by UUID id. A fresh process (every
start.sh boot) re-imports this module and resets every dict to empty. NOTHING is
seeded here — tests build all state via the API.
"""
import uuid
from datetime import timezone

import clock


# One dict per entity type, keyed by id.
clients = {}
projects = {}
proposals = {}
line_items = {}
racks = {}
devices = {}
scenes = {}
visits = {}
crew_members = {}
assignments = {}
contracts = {}
firmware_updates = {}
rma_tickets = {}
change_orders = {}


def _iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Monotone sequence so list ordering by creation is deterministic even when two
# resources share the same logical-clock millisecond.
_seq = {"n": 0}


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def stamp_create(entity):
    """Attach common fields on creation (PRD §2.4).

    id (UUID, no prefix), created_at, updated_at (ISO8601 UTC, 3 fractional
    digits), version (starts at 1).
    """
    ts = _iso(clock.now())
    entity["id"] = entity.get("id") or new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = _next_seq()
    return entity


def touch(entity):
    """Mutation: refresh updated_at and bump version (PRD §2.4, §2.6)."""
    entity["updated_at"] = _iso(clock.now())
    entity["version"] = entity.get("version", 1) + 1
    return entity
