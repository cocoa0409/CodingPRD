"""In-memory data store.

The store starts EMPTY on every boot — no seeding, ever. Every entity any
test needs is constructed through the declared API surface.

Contract relied upon by sibling modules:
  - store: dict of collection-name -> {id: entity-dict}
  - new_id() -> str        (uuid4, no type prefix)
  - now_iso() -> str       (logical clock, ISO8601 UTC, 3 fractional digits)
  - touch(entity)          (updated_at = now_iso(), version += 1)
"""

import uuid

from clock import get_now, format_iso

store = {
    "properties": {},
    "jurisdiction_policies": {},
    "banner_configs": {},
    "vendors": {},
    "tag_rules": {},
    "visitors": {},
    "gpc_events": {},
    "consent_records": {},
    "dns_requests": {},
    "vendor_propagations": {},
    "tag_audit_scans": {},
    "tracker_findings": {},
    "regulatory_sweeps": {},
}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical-clock now, ISO 8601 UTC with exactly three fractional digits."""
    return format_iso(get_now())


def touch(entity):
    """Refresh updated_at and increment the optimistic-concurrency version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
