"""Cascading side effects (PRD §2.8).

Each cascade independently mutates every affected resource — refreshing its
updated_at and incrementing its version — exactly as if the change had been
requested directly.
"""
from db import db, touch
from services.store import card_transactions


def end_assignment(assignment):
    """ACTIVE -> ENDED; stamps effective_to from the logical clock when it was null."""
    if assignment["status"] != "ACTIVE":
        return
    assignment["status"] = "ENDED"
    if assignment["effective_to"] is None:
        assignment["effective_to"] = db.clock.now_iso()
        assignment["_effective_to_dt"] = db.clock.now()
    touch(assignment)


def end_assignments_of_card(card_id):
    for assignment in list(db.card_assignments.values()):
        if assignment["card_id"] == card_id and assignment["status"] == "ACTIVE":
            end_assignment(assignment)


def end_assignments_of_vehicle(vehicle_id):
    for assignment in list(db.card_assignments.values()):
        if assignment["vehicle_id"] == vehicle_id and assignment["status"] == "ACTIVE":
            end_assignment(assignment)


def void_transaction(txn):
    """AUTHORIZED/CAPTURED -> VOIDED.  The hold is released and any accrued
    provisional rebate falls out of the account's rebate liability (both are
    reconciled from posting_status, see services/ledger.py)."""
    if txn["posting_status"] not in ("AUTHORIZED", "CAPTURED"):
        return
    txn["posting_status"] = "VOIDED"
    touch(txn)


def suspend_card(card):
    """ACTIVE -> SUSPENDED, voiding the card's open transactions."""
    card["status"] = "SUSPENDED"
    touch(card)
    for txn in sorted(card_transactions(card["id"]), key=lambda t: t["_seq"]):
        if txn["posting_status"] in ("AUTHORIZED", "CAPTURED"):
            void_transaction(txn)


def cancel_card(card):
    """-> CANCELLED (terminal), ending the card's ACTIVE assignments."""
    card["status"] = "CANCELLED"
    touch(card)
    end_assignments_of_card(card["id"])


def vehicle_out_of_service(vehicle):
    """ACTIVE -> OUT_OF_SERVICE, ending the vehicle's ACTIVE assignments."""
    if vehicle["status"] != "ACTIVE":
        return
    vehicle["status"] = "OUT_OF_SERVICE"
    touch(vehicle)
    end_assignments_of_vehicle(vehicle["id"])


def retire_vehicle(vehicle):
    """ACTIVE/OUT_OF_SERVICE -> RETIRED, ending the vehicle's ACTIVE assignments."""
    vehicle["status"] = "RETIRED"
    touch(vehicle)
    end_assignments_of_vehicle(vehicle["id"])


def restore_vehicle_if_clear(vehicle):
    """OUT_OF_SERVICE -> ACTIVE when no other fault on the vehicle remains in
    OPEN or MAINTENANCE_SCHEDULED (PRD §3.7)."""
    if vehicle["status"] != "OUT_OF_SERVICE":
        return
    blocking = [f for f in db.telematics_faults.values()
                if f["vehicle_id"] == vehicle["id"]
                and f["status"] in ("OPEN", "MAINTENANCE_SCHEDULED")]
    if blocking:
        return
    vehicle["status"] = "ACTIVE"
    touch(vehicle)
