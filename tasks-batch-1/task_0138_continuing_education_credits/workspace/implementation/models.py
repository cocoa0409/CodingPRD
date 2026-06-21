"""Record construction and mutation helpers (common fields, PRD §2.4).

A "full" record carries id, created_at, updated_at, version. A "lightweight"
record (Certificate, Attestation) carries only id and created_at.

bump() advances updated_at and increments version on a full record — used on
every mutation that changes a resource, including cascaded child updates so each
gets its own timestamp/version bump (PRD §2.8).
"""

import clock
from util import new_id


def new_full_record():
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def new_lightweight_record():
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
    }


def bump(record):
    """Advance updated_at to the current clock and increment version."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
