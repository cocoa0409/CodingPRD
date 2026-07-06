"""Cascading state propagation (PRD §2.9, §3.8, §3.9).

These functions implement the downward (attraction -> slots -> reservations ->
refunds) and the staffing-driven cascades. Every entity touched by a cascade
has its updated_at refreshed and its version incremented (PRD §2.9).
"""
import db
from services.common import touch, base_record


def pause_attraction_cascade(attraction, closure):
    """Run the Attraction OPEN->PAUSED pause cascade for `attraction`, attributing
    auto-refunds to `closure` (PRD §3.9, scaffold Attraction OPEN->PAUSED).

    L1: every SCHEDULED slot of the attraction -> CLOSED.
    L2: every reservation holding a ticket on a now-closed slot whose entry_status
        is HELD or RESERVED -> CANCELLED.
    L3: for each such cancelled reservation that was PAID -> payment_status
        REFUNDED, guest.wallet_credit_cents += total_cents, closure tally += 1.
    Attraction.status -> PAUSED; attraction.version incremented.
    """
    # L1: close scheduled slots.
    closed_slot_ids = set()
    for slot in db.time_slots.values():
        if slot["attraction_id"] == attraction["id"] and slot["status"] == "SCHEDULED":
            slot["status"] = "CLOSED"
            touch(slot)
            closed_slot_ids.add(slot["id"])

    # L2 + L3: cancel reservations holding tickets on now-closed slots.
    if closed_slot_ids:
        affected_reservation_ids = set()
        for ticket in db.tickets.values():
            if ticket["time_slot_id"] in closed_slot_ids:
                affected_reservation_ids.add(ticket["reservation_id"])

        for res_id in affected_reservation_ids:
            res = db.reservations.get(res_id)
            if res is None:
                continue
            if res["entry_status"] not in ("HELD", "RESERVED"):
                continue
            res["entry_status"] = "CANCELLED"
            # L3: refund a PAID reservation to the owning guest's wallet.
            if res["payment_status"] == "PAID":
                res["payment_status"] = "REFUNDED"
                guest = db.guests.get(res["guest_id"])
                if guest is not None:
                    guest["wallet_credit_cents"] += res["total_cents"]
                    touch(guest)
                closure["opened_reservation_refunds"] += 1
            touch(res)

    # Attraction -> PAUSED.
    attraction["status"] = "PAUSED"
    touch(attraction)


def open_understaffed_closure_and_pause(attraction):
    """Create an ACTIVE Closure(reason=UNDERSTAFFED) on `attraction` and run the
    pause cascade (PRD §3.8 check-out drop). Returns the created closure or None
    if the attraction is not OPEN.
    """
    if attraction["status"] != "OPEN":
        return None
    closure = base_record()
    closure.update({
        "attraction_id": attraction["id"],
        "reason": "UNDERSTAFFED",
        "opened_reservation_refunds": 0,
        "status": "ACTIVE",
    })
    db.closures[closure["id"]] = closure
    pause_attraction_cascade(attraction, closure)
    return closure
