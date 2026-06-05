"""In-memory data store (PRD: no durable storage; wiped on every boot).

Each entity collection is a dict keyed by its server-minted UUID id. There is
NO seeding — the store starts empty and every entity is built by tests via the
declared API surface.
"""
import uuid
from datetime import timezone

from timeutil import format_iso
import clock

# One dict per entity collection, keyed by id.
vendors = {}
employees = {}
software_products = {}
hardware_assets = {}
warranty_leases = {}
license_entitlements = {}
installation_records = {}
assignment_checkouts = {}
disposal_requests = {}
renewal_orders = {}
true_up_reconciliations = {}
compliance_findings = {}

# Monotonic creation sequence so list ordering by created_at is stable even
# when many records share the same millisecond timestamp.
_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def new_common(record):
    """Stamp id, created_at, updated_at, version=1, and a creation sequence.

    Used for entities that carry the common system-managed fields (PRD 2.5).
    """
    now = clock.get_now().astimezone(timezone.utc)
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = _next_seq()
    return record


def new_lean(record):
    """Stamp id and created_at only — for ComplianceFinding (PRD 2.5).

    A ComplianceFinding is immutable: no updated_at, no version.
    """
    now = clock.get_now().astimezone(timezone.utc)
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = _next_seq()
    return record


def touch(record):
    """Mark a common-field record as mutated: bump version, refresh updated_at.

    Whenever a derived field is recomputed as part of a request the owning
    resource is treated as mutated (PRD 2.6).
    """
    record["updated_at"] = clock.get_now().astimezone(timezone.utc)
    record["version"] = record.get("version", 1) + 1
    return record
