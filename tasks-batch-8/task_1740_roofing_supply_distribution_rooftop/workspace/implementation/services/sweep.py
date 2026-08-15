"""Clock-driven system transitions (PRD 2.4): re-evaluated on every logical
clock advance (and defensively before each request, which is a no-op when
nothing is due)."""
from datetime import timedelta

from db import db
from services.core import mutate
from util import CLOCK, parse_dt

TAKEOFF_DRAFT_TTL_DAYS = 30
TAKEOFF_QUOTED_TTL_DAYS = 14


def recompute_allocation_status(alloc):
    """Consumed share drives GRANTED -> PARTIALLY_CONSUMED -> CONSUMED (and
    the reverse when a confirmed order cancel returns consumption)."""
    if alloc["status"] in ("PENDING", "EXPIRED", "REVOKED"):
        return
    if alloc["granted_bundles"] > 0 and alloc["consumed_bundles"] >= alloc["granted_bundles"]:
        alloc["status"] = "CONSUMED"
    elif alloc["consumed_bundles"] > 0:
        alloc["status"] = "PARTIALLY_CONSUMED"
    else:
        alloc["status"] = "GRANTED"


def close_surge_event(event):
    """Shared close semantics (PRD 3.6): ACTIVE close expires live
    allocations and restores NORMAL mode; DECLARED close revokes PENDING
    allocations. Terminal CLOSED either way."""
    if event["status"] == "ACTIVE":
        branch = db["branches"].get(event["branch_id"])
        if branch is not None and branch["surge_mode"] == "SURGE":
            branch["surge_mode"] = "NORMAL"
            mutate(branch)
        for alloc in db["allocations"].values():
            if (alloc["storm_surge_event_id"] == event["id"]
                    and alloc["status"] in ("PENDING", "GRANTED", "PARTIALLY_CONSUMED")):
                released = alloc["granted_bundles"] - alloc["consumed_bundles"]
                if released:
                    event["allocated_bundles"] -= released
                alloc["status"] = "EXPIRED"
                mutate(alloc)
    elif event["status"] == "DECLARED":
        for alloc in db["allocations"].values():
            if (alloc["storm_surge_event_id"] == event["id"]
                    and alloc["status"] == "PENDING"):
                alloc["status"] = "REVOKED"
                mutate(alloc)
    else:
        return
    event["status"] = "CLOSED"
    mutate(event)


def sweep():
    """Evaluate every time-dependent system transition against the clock."""
    now = CLOCK.now()

    # Takeoff expiry: DRAFT ages out 30 days after creation; QUOTED ages out
    # 14 days after its last update (PRD 3.3). "Passes" = strictly later.
    for t in db["takeoffs"].values():
        if t["status"] == "DRAFT":
            if now > parse_dt(t["created_at"]) + timedelta(days=TAKEOFF_DRAFT_TTL_DAYS):
                t["status"] = "EXPIRED"
                mutate(t)
        elif t["status"] == "QUOTED":
            if now > parse_dt(t["updated_at"]) + timedelta(days=TAKEOFF_QUOTED_TTL_DAYS):
                t["status"] = "EXPIRED"
                mutate(t)

    # Surge lifecycle: DECLARED -> ACTIVE at starts_at; ACTIVE -> CLOSED at
    # ends_at (PRD 3.6). Process in creation order so activation-then-close
    # composes correctly when the clock jumps past the whole window.
    events = sorted(db["surge_events"].values(), key=lambda e: (e["created_at"], e["_seq"]))
    for ev in events:
        if ev["status"] == "DECLARED" and now >= parse_dt(ev["starts_at"]):
            ev["status"] = "ACTIVE"
            mutate(ev)
            branch = db["branches"].get(ev["branch_id"])
            if branch is not None:
                branch["surge_mode"] = "SURGE"
                mutate(branch)
        if ev["status"] == "ACTIVE" and now >= parse_dt(ev["ends_at"]):
            close_surge_event(ev)
