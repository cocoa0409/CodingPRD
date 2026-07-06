"""Common-field stamping + lookup helpers.

System fields (PRD §2.4):
  - id: server-minted UUID (no prefix)
  - created_at: fixed at creation
  - updated_at: refreshed on every mutation
  - version: starts at 1, +1 on every mutation
Internal datetime values are stored as tz-aware datetimes under '_created_at' /
'_updated_at' and serialized lazily.
"""
import db
import clock
from util import new_id
from errors import err, ERR_NOT_FOUND


def stamp_new(extra_fields, with_version=True):
    """Build a fresh entity dict with common system fields.

    The logical clock governs domain time, but created_at/updated_at are real
    wall-clock-independent server timestamps drawn from the logical clock so
    that creation ordering is deterministic in time-set tests. We use the
    logical clock for these stamps (PRD §2.8 makes the logical clock the single
    time source the server reasons about).
    """
    now = clock.now()
    e = {"id": new_id(), "_created_at": now, "_seq": db.next_seq()}
    if with_version:
        e["_updated_at"] = now
        e["version"] = 1
    e.update(extra_fields)
    return e


def touch(e):
    """Refresh updated_at and bump version by one (PRD §2.4 / §2.5)."""
    e["_updated_at"] = clock.now()
    e["version"] = e.get("version", 0) + 1


def must_get(collection, entity_id, label="resource"):
    """Fetch by id or raise ERR_NOT_FOUND (PRD §2.7 step 4)."""
    e = collection.get(entity_id)
    if e is None:
        raise err(ERR_NOT_FOUND, "No such %s: %s" % (label, entity_id))
    return e
