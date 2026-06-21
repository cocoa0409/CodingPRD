"""In-memory data store.

PRD §2.4: full first-class records carry id (UUID, no prefix), created_at,
updated_at, version (begins at 1, increments on every mutation). MeterRead and
Payment are append-only and carry only id and created_at.

Storage is in-memory only (dicts keyed by id). The store starts EMPTY on every
boot — nothing is seeded. Per-test-server isolation wipes all state on each
launch, so a fresh process == a fresh, empty store.
"""
import itertools
import uuid
from datetime import datetime, timezone

import clock

# One dict per entity type, keyed by id.
rate_schedules = {}
accounts = {}
meters = {}
meter_reads = {}
billing_cycles = {}
bills = {}
budget_plans = {}
assistance_enrollments = {}
leak_adjustments = {}
shutoff_orders = {}
payments = {}
moratoriums = {}

# Monotonic sequence used only as an internal creation-order tie-break so that
# "oldest-first" / "chronological by created_at ASC" orderings are stable even
# when two records share an identical created_at wall-clock string.
_seq = itertools.count(1)


def reset():
    """Wipe every store. Called at process import; no seeding occurs."""
    for store in (
        rate_schedules, accounts, meters, meter_reads, billing_cycles,
        bills, budget_plans, assistance_enrollments, leak_adjustments,
        shutoff_orders, payments, moratoriums,
    ):
        store.clear()
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def _now_iso():
    # created_at / updated_at are ISO 8601 UTC with three fractional digits.
    # These are real wall-clock stamps, independent of the logical clock.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)


def make_record(fields, append_only=False):
    """Create a record with system-managed common fields.

    append_only=True -> id + created_at only (MeterRead, Payment).
    Otherwise -> id, created_at, updated_at, version (begins at 1).
    """
    rid = new_id()
    ts = _now_iso()
    rec = {"id": rid, "created_at": ts}
    rec["_seq"] = next_seq()  # internal ordering aid; stripped from output
    if not append_only:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a full record mutated: bump updated_at and version (PRD §2.4)."""
    rec["updated_at"] = _now_iso()
    rec["version"] = rec.get("version", 1) + 1
