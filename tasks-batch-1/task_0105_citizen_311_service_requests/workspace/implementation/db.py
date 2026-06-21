"""In-memory data store. Starts EMPTY on every boot — no seeding.

Each entity collection is a dict keyed by id. The store also owns the single
logical clock. Common-field management (id/created_at/updated_at/version) lives
here so every mutation goes through one place.
"""
import uuid

import clock as clockmod

# ---- Entity collections (all empty at boot) ----
categories = {}        # ServiceCategory
jurisdictions = {}     # Jurisdiction
departments = {}       # Department
sla_policies = {}      # SlaPolicy
citizens = {}          # Citizen
agents = {}            # Agent
service_requests = {}  # ServiceRequest
clusters = {}          # DuplicateCluster
work_orders = {}       # WorkOrder
escalations = {}       # Escalation (append-only: id + created_at; mutable status/resolved_by_role)
notifications = {}     # StatusNotification (append-only: id + created_at)
surveys = {}           # SatisfactionSurvey
windows = {}           # ServiceWindow

# Monotonic sequence to break created_at ties deterministically (same-instant
# inserts retain insertion order; created_at ASC ordering uses (created_at, seq)).
_seq_counter = {"n": 0}

CLOCK = clockmod.Clock()


def reset():
    """Wipe all state. (Defensive — process restart already gives a clean store.)"""
    for coll in (categories, jurisdictions, departments, sla_policies, citizens,
                 agents, service_requests, clusters, work_orders, escalations,
                 notifications, surveys, windows):
        coll.clear()
    _seq_counter["n"] = 0


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def stamp_common(record):
    """Attach id, created_at, updated_at, version for full-common-field entities."""
    record["id"] = new_id()
    ts = CLOCK.now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = _next_seq()
    return record


def stamp_audit(record):
    """Attach id, created_at only for append-only entities (no updated_at/version)."""
    record["id"] = new_id()
    record["created_at"] = CLOCK.now_iso()
    record["_seq"] = _next_seq()
    return record


def touch(record):
    """Bump updated_at + version on a full-common-field entity (every mutation)."""
    record["updated_at"] = CLOCK.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def ordered(collection, predicate=None):
    """Return records in created_at ASC order, optionally filtered.

    created_at is stamped from the logical clock, which a SystemAdmin can move
    backward; that would make a raw created_at string sort disagree with the
    actual chronological insertion order. The monotonic _seq counter records true
    insertion order, so we sort by _seq (the deterministic realization of
    "created_at ascending"). For records minted at the same logical instant this
    is identical to a created_at sort, and it stays correct under clock jumps.
    """
    rows = list(collection.values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows
