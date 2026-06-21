"""In-memory data store.

The store starts EMPTY on every boot. No entities are seeded, preloaded, or
hardcoded at startup. Every entity is constructed by tests via the declared
API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

from timeutil import iso_now

# One dict per entity type, keyed by id.
borrowers = {}
regulatory_profiles = {}
vehicles = {}
appraisals = {}
applications = {}
loans = {}
title_liens = {}
installments = {}
payments = {}
renewals = {}
repossession_orders = {}
assignments = {}
devices = {}
device_commands = {}

# Monotonic creation sequence so list ordering by creation time is stable even
# when several entities are created within the same millisecond (PRD 2.3).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def common_fields(with_version=True):
    """Build the system common fields for a new resource (PRD 2.4).

    created_at/updated_at use real wall-clock time (audit metadata), not the
    test clock — the test clock governs domain time-gated logic only (PRD 2.10).
    """
    now = iso_now(datetime.now(timezone.utc))
    fields = {
        "id": new_id(),
        "created_at": now,
        "_seq": next_seq(),
    }
    if with_version:
        fields["updated_at"] = now
        fields["version"] = 1
    return fields


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD 2.4, 2.9)."""
    entity["updated_at"] = iso_now(datetime.now(timezone.utc))
    entity["version"] = entity.get("version", 1) + 1
