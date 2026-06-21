"""Transfer (delivery) transitions (PRD §3.6)."""
import db
import clock
import errors
from errors import err
from services import calc, recompute, seat_ops


def initiate(order, listing, event):
    """Create a Transfer in INITIATED for a charged order.
    delivery_status must be AWAITING or DELIVERY_FAILED; payment must be CHARGED."""
    if order["payment_status"] != "CHARGED":
        raise err(errors.ERR_DELIVERY_BEFORE_PAYMENT, "Order is not charged")
    if order["delivery_status"] not in ("AWAITING", "DELIVERY_FAILED"):
        raise err(errors.ERR_INVALID_STATE,
                  "Cannot initiate transfer from delivery_status %s" % order["delivery_status"])

    # attempt_number: prior max + 1, else 1
    prior = [t for t in db.transfers.values() if t["order_id"] == order["id"]]
    attempt_number = (max((t["attempt_number"] for t in prior), default=0)) + 1

    now = clock.now()
    doors = clock.parse_iso(event["doors_open_at"])
    is_last_minute = calc.transfer_is_last_minute(
        now, doors, event["last_minute_cutoff_minutes"]
    )

    transfer = {
        "order_id": order["id"],
        "method": listing["delivery_method"],
        "status": "INITIATED",
        "is_last_minute": is_last_minute,
        "deadline_at": None,
        "attempt_number": attempt_number,
    }
    db.stamp_create(transfer)
    db.transfers[transfer["id"]] = transfer
    return transfer


def send(transfer, order, event):
    if transfer["status"] != "INITIATED":
        raise err(errors.ERR_INVALID_STATE, "Transfer is not INITIATED")
    if order["payment_status"] != "CHARGED":
        raise err(errors.ERR_DELIVERY_BEFORE_PAYMENT, "Order is not charged")

    now = clock.now()
    doors = clock.parse_iso(event["doors_open_at"])
    # recompute is_last_minute at send time
    is_lm = calc.transfer_is_last_minute(now, doors, event["last_minute_cutoff_minutes"])
    transfer["is_last_minute"] = is_lm
    deadline = calc.transfer_deadline(now, is_lm, doors)
    transfer["deadline_at"] = clock.to_iso(deadline)
    transfer["status"] = "SENT"
    db.touch(transfer)

    if order["delivery_status"] in ("AWAITING", "DELIVERY_FAILED"):
        order["delivery_status"] = "IN_TRANSFER"
        recompute.recompute_order_lifecycle(order)
        db.touch(order)


def accept(transfer, order):
    if transfer["status"] != "SENT":
        raise err(errors.ERR_INVALID_STATE, "Transfer is not SENT")
    if clock.now() >= clock.parse_iso(transfer["deadline_at"]):
        raise err(errors.ERR_TRANSFER_DEADLINE_PASSED, "Transfer deadline has passed")

    transfer["status"] = "ACCEPTED"
    db.touch(transfer)

    order["delivery_status"] = "DELIVERED"
    for seat in seat_ops.seats_for_order(order["id"]):
        if seat["status"] == "SOLD":
            seat_ops.set_status(seat, "TRANSFERRED")
    recompute.recompute_order_lifecycle(order)
    db.touch(order)


def fail(transfer, order):
    if transfer["status"] not in ("INITIATED", "SENT"):
        raise err(errors.ERR_INVALID_STATE, "Transfer is not INITIATED/SENT")
    transfer["status"] = "FAILED"
    db.touch(transfer)
    order["delivery_status"] = "DELIVERY_FAILED"
    recompute.recompute_order_lifecycle(order)
    db.touch(order)


def recall(transfer, order):
    if transfer["status"] != "SENT":
        raise err(errors.ERR_INVALID_STATE, "Transfer is not SENT")
    if clock.now() >= clock.parse_iso(transfer["deadline_at"]):
        raise err(errors.ERR_TRANSFER_DEADLINE_PASSED, "Transfer deadline has passed")
    transfer["status"] = "RECALLED"
    db.touch(transfer)
    order["delivery_status"] = "AWAITING"
    recompute.recompute_order_lifecycle(order)
    db.touch(order)
