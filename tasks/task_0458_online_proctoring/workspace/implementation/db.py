"""In-memory data store.

All storage is in-memory only — plain Python dicts keyed by id. The store
starts EMPTY on every boot; no entity is ever seeded, preloaded, or
hardcoded. Every entity is constructed by a declared endpoint.

Re-invoking start.sh launches a fresh process, so module-level state here is
wiped on every restart automatically.
"""
import uuid

from clock import format_iso, now_iso_realish
from datetime import datetime, timezone


# One dict per entity collection, keyed by id.
institutions = {}
proctors = {}
candidates = {}
exams = {}
accommodations = {}
appointments = {}
identity_verifications = {}
sessions = {}
incident_flags = {}
escalations = {}
integrity_reports = {}
retake_authorizations = {}

# Monotonic creation sequence so that created_at ties (same-millisecond
# inserts) still sort deterministically in creation order (PRD §2.3 sorts by
# created_at ascending; we keep an insertion-order tiebreaker).
_seq_counter = 0


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def _next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def system_now_iso():
    """Real-time ISO stamp (3 fractional digits) used for created_at/updated_at.

    created_at/updated_at are wall-clock audit stamps (PRD §2.4), independent
    of the logical clock used for temporal gates.
    """
    return format_iso(datetime.now(timezone.utc))


def stamp_create(record, versioned=True):
    """Attach system audit fields on creation.

    versioned=True -> created_at, updated_at, version (the 10 full-triple
    resources). versioned=False -> created_at only (IdentityVerification,
    IncidentFlag append-only records).
    """
    now = system_now_iso()
    record["created_at"] = now
    record["_seq"] = _next_seq()
    if versioned:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version by exactly 1 (PRD §2.4)."""
    record["updated_at"] = system_now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
