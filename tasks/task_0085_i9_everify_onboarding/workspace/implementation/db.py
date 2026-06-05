"""In-memory data store. Wiped on every process start — no persistence.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded here; every entity is built by a test via the declared endpoints.

Common-field conventions (PRD §2.4):
  - id            : UUID4 string, no type prefix
  - created_at    : ISO timestamp set on create
  - updated_at    : ISO timestamp refreshed on every mutation
  - version       : integer starting at 1, +1 on every mutation
AuditEntry is the exception: only id + created_at, no updated_at / version.
"""

import uuid

from clock import now, format_iso8601


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.onboardings = {}
        self.i9_forms = {}
        self.identity_documents = {}
        self.everify_cases = {}
        self.work_authorizations = {}
        self.reverification_events = {}
        self.audit_entries = {}
        # Monotonic insertion sequence so created_at ties keep stable ordering.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Set id/created_at/updated_at/version + insertion sequence."""
    ts = format_iso8601(now())
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_audit_create(record):
    """AuditEntry: only id + created_at (PRD §2.4)."""
    record.setdefault("id", new_id())
    record["created_at"] = format_iso8601(now())
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.4 / §2.9)."""
    record["updated_at"] = format_iso8601(now())
    record["version"] = record.get("version", 1) + 1
