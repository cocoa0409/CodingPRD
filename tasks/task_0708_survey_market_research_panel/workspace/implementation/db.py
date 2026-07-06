"""In-memory data store (PRD §2.4 — UUID ids, logical-clock timestamps).

Storage is process-local dicts keyed by id. The store starts EMPTY on every
boot — nothing is seeded, preloaded, or hardcoded. Every entity is created by
a test via the declared API surface. `--isolation per-test-server` restarts the
process before each test, wiping all of this.

Each collection is keyed by entity id. A monotonic insertion counter (`_seq`)
records insertion order so list endpoints can sort by created_at ascending with
a stable tiebreak even when the logical clock does not advance between creates.
"""
import itertools
import uuid

import clock

# One dict per entity collection.
studies = {}
quota_cells = {}
panelists = {}
consents = {}
participations = {}
attention_checks = {}
incentive_accruals = {}
payout_requests = {}
facilities = {}
focus_groups = {}
focus_group_bookings = {}
data_deliveries = {}

_seq_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def base_record(common_fields=True):
    """Common system fields for a freshly created record.

    common_fields=True entities carry id, created_at, updated_at, version (§2.4).
    common_fields=False entities (Consent, AttentionCheck) are immutable audit
    records: only id and created_at, no updated_at, no version.
    """
    now = clock.now_iso()
    rec = {
        "id": new_id(),
        "created_at": now,
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at + version on a mutation of a common-fields entity."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 1) + 1
