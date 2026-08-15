"""In-memory data store. All state lives in Python dicts keyed by id.

The store starts completely empty on every boot — no seeding, no
preloading, no hardcoded entities. Every entity is constructed via the
declared API surface.
"""

import uuid
from datetime import datetime, timezone

from clock import iso_z


def new_id():
    return str(uuid.uuid4())


def wall_timestamp():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.2/§2.4)."""
    now = datetime.now(timezone.utc)
    return iso_z(now)


# Entity stores — keyed by id.
farms = {}
producers = {}
memberships = {}
tracts = {}
fields = {}
acreage_reports = {}
acreage_report_lines = {}
program_elections = {}
yield_records = {}
yield_observations = {}
enrollments = {}
disaster_applications = {}
appeals = {}
reconstitutions = {}

# Internal bookkeeping (never serialized): market inputs used by each
# enrollment's payment computation, so a disaster-approval cascade can
# recompute the payment delta (PRD §3.9).
enrollment_compute_inputs = {}


def common_fields():
    """Full common-field set (PRD §2.4): id, created_at, updated_at, version."""
    ts = wall_timestamp()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def observation_fields():
    """YieldObservation is exempt from the full contract (PRD §2.4):
    only id and created_at; updated_at and version are absent."""
    return {
        "id": new_id(),
        "created_at": wall_timestamp(),
    }


def touch(entity):
    """Bump updated_at and version on a mutated entity."""
    entity["updated_at"] = wall_timestamp()
    entity["version"] = entity.get("version", 1) + 1
