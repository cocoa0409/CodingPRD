"""In-memory data store (PRD §2.4).

ALL state lives in module-level dicts keyed by id. The store starts empty on
every boot; nothing is seeded. start.sh re-invocation launches a fresh process,
wiping all state.
"""

import uuid
import threading
from datetime import timezone

import clock

_lock = threading.RLock()


def lock():
    return _lock


# One dict per entity type, keyed by id.
practices = {}
providers = {}
modalities = {}
patients = {}
prior_authorizations = {}
encounters = {}
procedures = {}
orthotic_rxs = {}
lab_orders = {}
dme_dispenses = {}
imaging_orders = {}
referrals = {}
recalls = {}

# Monotonic sequence to break created_at ties for deterministic ordering.
_seq = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def iso_now():
    """ISO 8601 UTC timestamp with three fractional digits, from logical clock.

    Used for created_at / updated_at on entities so they track the logical clock
    (PRD §2.4 / §2.5: every date/time decision reads the logical clock).
    """
    dt = clock.now().astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_common(entity):
    """Set id/created_at/updated_at/version on a fresh entity."""
    ts = iso_now()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.9)."""
    entity["updated_at"] = iso_now()
    entity["version"] += 1
    return entity
