"""In-memory data store.

Storage is process-local Python dictionaries keyed by entity id.  The store is
EMPTY on every boot: nothing is seeded, preloaded or hardcoded.  Every entity is
created exclusively through the declared HTTP surface.
"""

import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

from response import iso_timestamp

# ---------------------------------------------------------------------------
# Collections (all empty at import time — never seeded)
# ---------------------------------------------------------------------------
bonus_plans = {}
company_metrics = {}
business_units = {}
job_level_targets = {}
participants = {}
eligibility_events = {}
bu_pools = {}
participant_awards = {}
discretionary_adjustments = {}
accrual_periods = {}
payout_runs = {}
disputes = {}

_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# Server-side logical clock (PRD 2.4).  Default 2026-08-01T00:00:00Z.
# Never the host wall clock for date comparisons.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"current_utc": DEFAULT_CLOCK}


def clock_now():
    return _clock["current_utc"]


def set_clock(dt):
    _clock["current_utc"] = dt


def logical_today():
    """The current logical date (UTC calendar day of the logical clock)."""
    return clock_now().astimezone(timezone.utc).date()


# ---------------------------------------------------------------------------
# Identity / system field helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_record(versioned=True):
    """id + created_at (+ updated_at/version when the entity carries them)."""
    stamp = iso_timestamp()
    rec = {"id": new_id(), "_seq": next_seq(), "created_at": stamp}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at for a write that changed a stored field."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = iso_timestamp()


_VOLATILE = ("version", "updated_at", "_seq")


def snapshot(rec):
    return {k: v for k, v in rec.items() if k not in _VOLATILE}


def bump_if_changed(rec, before):
    """Version/timestamp bump only when a stored field actually changed."""
    if snapshot(rec) != before:
        touch(rec)
        return True
    return False


# ---------------------------------------------------------------------------
# Ordered access.  created_at ASC is the only permitted fallback order
# (PRD 2.3); `_seq` is the monotonic insertion tiebreaker.
# ---------------------------------------------------------------------------
def ordered(collection):
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


# ---------------------------------------------------------------------------
# Scoped queries
# ---------------------------------------------------------------------------
def plan_metrics(plan_id):
    return [m for m in ordered(company_metrics) if m["plan_id"] == plan_id]


def plan_targets(plan_id):
    return [t for t in ordered(job_level_targets) if t["plan_id"] == plan_id]


def target_for_level(plan_id, job_level):
    for t in ordered(job_level_targets):
        if t["plan_id"] == plan_id and t["job_level"] == job_level:
            return t
    return None


def plan_participants(plan_id):
    return [p for p in ordered(participants) if p["plan_id"] == plan_id]


def plan_pools(plan_id):
    return [p for p in ordered(bu_pools) if p["plan_id"] == plan_id]


def pool_for_unit(plan_id, business_unit_id):
    for p in ordered(bu_pools):
        if p["plan_id"] == plan_id and p["business_unit_id"] == business_unit_id:
            return p
    return None


def plan_awards(plan_id):
    return [a for a in ordered(participant_awards) if a["plan_id"] == plan_id]


def pool_awards(pool_id):
    return [a for a in ordered(participant_awards) if a["bu_pool_id"] == pool_id]


def award_for_participant(participant_id):
    for a in ordered(participant_awards):
        if a["participant_id"] == participant_id:
            return a
    return None


def participant_events(participant_id):
    return [e for e in ordered(eligibility_events)
            if e["participant_id"] == participant_id]


def live_events(participant_id):
    """Non-superseded events of a participant, effective_date ASC / created_at ASC."""
    evs = [e for e in eligibility_events.values()
           if e["participant_id"] == participant_id and not e["superseded"]]
    evs.sort(key=lambda e: (e["effective_date"], e["_seq"]))
    return evs


def award_adjustments(award_id):
    return [a for a in ordered(discretionary_adjustments)
            if a["award_id"] == award_id]


def plan_adjustments(plan_id):
    return [a for a in ordered(discretionary_adjustments)
            if a["plan_id"] == plan_id]


def plan_periods(plan_id):
    return [p for p in ordered(accrual_periods) if p["plan_id"] == plan_id]


def plan_payout_runs(plan_id):
    return [p for p in ordered(payout_runs) if p["plan_id"] == plan_id]


def award_disputes(award_id):
    return [d for d in ordered(disputes) if d["award_id"] == award_id]


def plan_disputes(plan_id):
    return [d for d in ordered(disputes) if d["plan_id"] == plan_id]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def as_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def day_after(d):
    return d + timedelta(days=1)
