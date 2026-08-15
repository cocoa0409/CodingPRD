"""Core record helpers and the shared cascade mechanics (PRD 2.4, 3.2, 3.3, 3.5).

Versioning rule (PRD 2.4): any mutation — a state transition, an amendment, a
counter recomputation, or one hop of a multi-resource cascade — increments the
affected resource's version by exactly one and refreshes updated_at. All
entity timestamps come from the logical clock.
"""
from db import db, next_seq
from util import CLOCK, new_id


def stamp_new(rec):
    """Assign identity + common system fields to a freshly built record."""
    now = CLOCK.now_iso()
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """One mutation hop: version += 1 and updated_at := logical clock reading."""
    rec["version"] += 1
    rec["updated_at"] = CLOCK.now_iso()


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Supply cascade primitives (PRD 3.5)
# ---------------------------------------------------------------------------

def distribution_for_event(event_id):
    for d in db["supplies"].values():
        if d["event_id"] == event_id:
            return d
    return None


def restock_depot(depot, vests, grabbers):
    """Return units to on-hand; the depot mutation bumps its own version."""
    if vests or grabbers:
        depot["vests_on_hand"] += vests
        depot["grabbers_on_hand"] += grabbers
        touch(depot)


def reconcile_distribution_gentle(dist):
    """System cascade path (event cancel / no-show / agreement suspend or
    terminate): outstanding returnables are treated as returned, restocked to
    the issuing depot, and zero loss is recorded (PRD 3.2/3.3/3.5)."""
    if dist["status"] not in ("ISSUED", "PARTIALLY_RETURNED"):
        return
    out_v = dist["vests_issued"] - dist["vests_returned"] - dist["lost_vests"]
    out_g = dist["grabbers_issued"] - dist["grabbers_returned"] - dist["lost_grabbers"]
    dist["vests_returned"] += out_v
    dist["grabbers_returned"] += out_g
    dist["status"] = "RECONCILED"
    touch(dist)
    depot = db["depots"].get(dist["depot_id"])
    if depot is not None:
        restock_depot(depot, out_v, out_g)


def cancel_event_cascade(ev):
    """CleanupEvent -> CANCELLED with its supply distribution reconciled and
    restocked (no loss). Caller guarantees the event is non-terminal."""
    ev["status"] = "CANCELLED"
    touch(ev)
    dist = distribution_for_event(ev["id"])
    if dist is not None:
        reconcile_distribution_gentle(dist)


def noshow_event_cascade(ev):
    ev["status"] = "NO_SHOW"
    touch(ev)
    dist = distribution_for_event(ev["id"])
    if dist is not None:
        reconcile_distribution_gentle(dist)


# ---------------------------------------------------------------------------
# Agreement cascades (PRD 3.2)
# ---------------------------------------------------------------------------

def events_of_agreement(agreement_id):
    return [e for e in db["events"].values() if e["agreement_id"] == agreement_id]


def signs_of_agreement(agreement_id):
    return [s for s in db["signs"].values() if s["agreement_id"] == agreement_id]


def remove_installed_signs(agreement_id):
    for s in signs_of_agreement(agreement_id):
        if s["status"] == "INSTALLED":
            s["status"] = "REMOVED"
            touch(s)


def free_segment(agreement):
    seg = db["segments"].get(agreement["segment_id"])
    if seg is not None and seg["status"] != "AVAILABLE":
        seg["status"] = "AVAILABLE"
        touch(seg)


def suspend_cascade(agreement):
    """ACTIVE -> SUSPENDED (PRD 3.2): cancels SCHEDULED/POSTPONED child events
    (BRIEFING_DONE deliberately untouched), reconciles their distributions with
    full restock and no loss, refreshes the depot."""
    for ev in events_of_agreement(agreement["id"]):
        if ev["status"] in ("SCHEDULED", "POSTPONED"):
            cancel_event_cascade(ev)


def terminate_cascade(agreement):
    """-> TERMINATED (PRD 3.2): every non-terminal child event cancelled with
    reconcile+restock, any INSTALLED sign REMOVED, the segment freed."""
    for ev in events_of_agreement(agreement["id"]):
        if ev["status"] in ("SCHEDULED", "BRIEFING_DONE", "POSTPONED"):
            cancel_event_cascade(ev)
    remove_installed_signs(agreement["id"])
    free_segment(agreement)


def expire_cascade(agreement):
    """-> EXPIRED (renewal denial or term-end sweep): segment freed and any
    INSTALLED sign REMOVED. No event cascade on expiry (PRD 3.8)."""
    remove_installed_signs(agreement["id"])
    free_segment(agreement)
