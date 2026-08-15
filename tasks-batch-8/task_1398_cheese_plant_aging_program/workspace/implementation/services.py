"""Cross-entity services: ledger syncs, cascades, status re-derivation."""

from calc import D, derive_posture, turns_due as compute_turns_due, age_days as compute_age_days
from db import STORES, now, touch

ACTIVE_MAKE_STATES = ("SCHEDULED", "IN_PROGRESS", "CURD_READY")


def active_makes_on_vat(vat_id):
    return [
        m
        for m in STORES["make_sheets"].values()
        if m["vat_id"] == vat_id and m["status"] in ACTIVE_MAKE_STATES
    ]


def rederive_vat_status(vat):
    """The vat returns to IDLE only when its last active make completes or is
    cancelled; with a queue still active it stays BOOKED (PRD 3.3)."""
    if vat["status"] in ("DECOMMISSIONED", "CLEANING"):
        return
    vat["status"] = "BOOKED" if active_makes_on_vat(vat["id"]) else "IDLE"


def refresh_room_posture(room):
    room["posture"] = derive_posture(room)


def rederive_order_status(order):
    cut = order["wheels_cut"]
    requested = order["wheels_requested"]
    if cut == 0:
        order["status"] = "OPEN"
    elif cut < requested:
        order["status"] = "PARTIALLY_FILLED"
    else:
        order["status"] = "FILLED"


def condemn_batch(batch):
    """CONDEMNED cascade (PRD 3.7): batch terminal, release REJECTED, every
    OPEN/PARTIALLY_FILLED allocation order against the batch is cancelled;
    FILLED orders are retained for traceability."""
    batch["status"] = "CONDEMNED"
    batch["release_decision"] = "REJECTED"
    for order in STORES["allocation_orders"].values():
        if order["cheese_batch_id"] == batch["id"] and order["status"] in (
            "OPEN",
            "PARTIALLY_FILLED",
        ):
            order["status"] = "CANCELLED"
            touch(order)


def unit_variety(unit):
    batch = STORES["cheese_batches"].get(unit["cheese_batch_id"])
    return batch["variety"] if batch else None


def unit_age_days(unit):
    return compute_age_days(unit["_entered_dt"], now())


def unit_turns_due(unit):
    variety = unit_variety(unit)
    if variety is None:
        return False
    return compute_turns_due(unit["_last_turned_dt"], now(), variety)


def refill_lot_if_live(lot, amount):
    """Compensating reversal on cancel: applies only to non-terminal lots.
    A DEPLETED lot returns to RELEASED when the refund lifts it above zero;
    EXPIRED/RECALLED lots are settled history and are never rewritten."""
    if lot["status"] not in ("RELEASED", "DEPLETED"):
        return
    lot["quantity_on_hand"] = float(D(lot["quantity_on_hand"]) + D(amount))
    if lot["status"] == "DEPLETED" and D(lot["quantity_on_hand"]) > 0:
        lot["status"] = "RELEASED"
    touch(lot)


def uncommit_milk_if_live(intake, liters):
    """Milk un-commit on cancel applies only while the intake is non-terminal
    (a CONSUMED intake is settled history, PRD 2.5)."""
    if intake["status"] == "CONSUMED":
        return
    intake["consumed_liters"] = float(D(intake["consumed_liters"]) - D(liters))
    touch(intake)
