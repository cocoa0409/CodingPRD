"""Cascade helpers: signup cancellation side effects, event cancellation cascade,
suspension cascade, revocation of distributions."""
from db import store
from services.core import touch, NON_TERMINAL_SIGNUP
from services.seat_open import seat_open_handling


def revoke_distributions_for_signup(signup):
    """ISSUED distributions of this signup -> REVOKED (inventory count recomputed on read)."""
    for dr in store.distribution_records.values():
        if dr["signup_id"] == signup["id"] and dr["status"] == "ISSUED":
            dr["status"] = "REVOKED"
            touch(dr)
            if dr["kind"] == "SUPPLY_ITEM" and dr.get("inventory_id"):
                inv = store.supply_inventories.get(dr["inventory_id"])
                if inv is not None:
                    touch(inv)


def cancel_signup_record(signup, fire_seat_open=True):
    """Cancel a single signup record (REQUESTED|WAITLISTED|APPROVED|CONFIRMED).
    Releases captain flag; frees seat and fires seat-open handling when a seat was occupied.
    Does NOT handle CHECKED_IN (event cascade path handles those separately)."""
    was_occupying = signup["status"] in {"APPROVED", "CONFIRMED"}
    signup["status"] = "CANCELLED"
    if signup.get("is_captain"):
        signup["is_captain"] = False
    touch(signup)
    if was_occupying:
        revoke_distributions_for_signup(signup)
        shift = store.shifts.get(signup["shift_id"])
        if shift is not None and fire_seat_open:
            seat_open_handling(shift, freed_signup=signup)


def event_cancel_cascade(event):
    """Full 3-link cascade for event cancellation."""
    # link 1: shifts OPEN|FULL|LOCKED|IN_PROGRESS -> CANCELLED
    affected_shifts = [
        s for s in store.shifts.values()
        if s["event_id"] == event["id"] and s["status"] in {"OPEN", "FULL", "LOCKED", "IN_PROGRESS"}
    ]
    for shift in affected_shifts:
        shift["status"] = "CANCELLED"
        touch(shift)
    # link 2: signups on ALL of this event's shifts in non-terminal status -> CANCELLED
    shift_ids = {s["id"] for s in store.shifts.values() if s["event_id"] == event["id"]}
    for su in list(store.signups.values()):
        if su["shift_id"] in shift_ids and su["status"] in NON_TERMINAL_SIGNUP:
            su["status"] = "CANCELLED"
            if su.get("is_captain"):
                su["is_captain"] = False
            touch(su)
            # link 3: revoke ISSUED distributions on every cancelled signup
            revoke_distributions_for_signup(su)


def suspension_cascade(volunteer):
    """ELIGIBLE -> SUSPENDED cascade: cancel APPROVED|CONFIRMED signups, fire seat-open per seat."""
    freed = []
    for su in list(store.signups.values()):
        if su["volunteer_id"] == volunteer["id"] and su["status"] in {"APPROVED", "CONFIRMED"}:
            su["status"] = "CANCELLED"
            if su.get("is_captain"):
                su["is_captain"] = False
            touch(su)
            revoke_distributions_for_signup(su)
            freed.append(su)
    for su in freed:
        shift = store.shifts.get(su["shift_id"])
        if shift is not None:
            seat_open_handling(shift, freed_signup=su)
