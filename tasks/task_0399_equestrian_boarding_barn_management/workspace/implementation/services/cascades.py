"""Cascade side-effects (PRD §2.9, §3.4, §3.5).

These are the system-driven ripples:
  - waiver expiry -> suspend ACTIVE agreements -> cancel future scheduled lessons
  - waiver re-sign -> reinstate eligible SUSPENDED agreements
  - agreement end -> cancel future booked turnouts

Each secondary resource mutated by a cascade gets its own updated_at refresh and
version bump, exactly as a direct mutation would (PRD §2.9).
"""
from clock import parse_iso, whole_days_between
from db import db
from services.common import touch
from services.standing import SUSPEND_SCORE


def _horse_ids_of_owner(owner_id):
    return {h["id"] for h in db.horses.values() if h["owner_id"] == owner_id}


def suspend_agreement_cascade(agreement):
    """ACTIVE -> SUSPENDED side-effects (PRD §3.5 'Suspending').
    Sets suspended_at; cancels the horse's future SCHEDULED lessons (starts_at >= now)
    with billed_fee_cents = 0. Caller has already set status = SUSPENDED and touched.
    Stall.occupied_count is unchanged (suspended horses keep their slot, PRD §3.2)."""
    now = db.clock.now
    for l in db.lessons.values():
        if l["horse_id"] != agreement["horse_id"]:
            continue
        if l["status"] != "SCHEDULED":
            continue
        if parse_iso(l["starts_at"]) >= now:
            l["status"] = "CANCELLED"
            l["billed_fee_cents"] = 0
            touch(l)


def waiver_expiry_cascade(owner):
    """Every ACTIVE BoardingAgreement of every horse owned by this owner transitions
    ACTIVE -> SUSPENDED (hop 1), which fires the lesson-cancellation cascade (hop 2)."""
    now = db.clock.now
    horse_ids = _horse_ids_of_owner(owner["id"])
    for a in db.agreements.values():
        if a["horse_id"] not in horse_ids:
            continue
        if a["status"] != "ACTIVE":
            continue
        a["status"] = "SUSPENDED"
        a["suspended_at"] = __import__("clock").format_iso(now)
        touch(a)
        suspend_agreement_cascade(a)


def waiver_resign_cascade(owner):
    """Every SUSPENDED BoardingAgreement of this owner's horses whose suspended_at is
    set transitions SUSPENDED -> ACTIVE, but only if Owner.standing_score < SUSPEND_SCORE.
    Accumulates suspended_days and clears suspended_at (PRD §3.4)."""
    if owner["standing_score"] >= SUSPEND_SCORE:
        return
    now = db.clock.now
    horse_ids = _horse_ids_of_owner(owner["id"])
    for a in db.agreements.values():
        if a["horse_id"] not in horse_ids:
            continue
        if a["status"] != "SUSPENDED":
            continue
        if not a["suspended_at"]:
            continue
        suspended = parse_iso(a["suspended_at"])
        a["suspended_days"] += whole_days_between(suspended, now)
        a["suspended_at"] = None
        a["status"] = "ACTIVE"
        touch(a)


def end_releases_turnouts_cascade(agreement):
    """Every BOOKED TurnoutAssignment of this horse with window_start >= now
    transitions BOOKED -> CANCELLED (PRD §3.5 'Ending')."""
    now = db.clock.now
    for t in db.turnouts.values():
        if t["horse_id"] != agreement["horse_id"]:
            continue
        if t["status"] != "BOOKED":
            continue
        if parse_iso(t["window_start"]) >= now:
            t["status"] = "CANCELLED"
            touch(t)
