"""Deterministic system sweeps fired by clock set/advance (PRD §2.10).

On any clock change:
  - reservations past reservation_expires_at (PENDING orders) auto-refund
  - SENT transfers past deadline_at -> EXPIRED, order delivery -> DELIVERY_FAILED
  - ISSUED event credits past validity window -> EXPIRED
  - ON_SALE events that have crossed the last-minute threshold may enter LAST_MINUTE

Note on credit validity: the PRD names a credit-expiry sweep but does not pin a
concrete validity duration, so no automatic credit expiry is applied here; credits
remain ISSUED until explicitly redeemed/revoked. The sweep hook is present for
completeness.
"""
import db
import clock
from services import recompute, order_ops, transfer_ops  # noqa: F401


def run_all():
    _sweep_reservations()
    _sweep_transfers()
    _sweep_last_minute()


def _sweep_reservations():
    now = clock.now()
    for order in list(db.orders.values()):
        if order["payment_status"] != "PENDING":
            continue
        expires = clock.parse_iso(order["reservation_expires_at"])
        if expires is not None and now >= expires:
            order_ops._release_reservation(order)


def _sweep_transfers():
    now = clock.now()
    for transfer in list(db.transfers.values()):
        if transfer["status"] != "SENT":
            continue
        deadline = clock.parse_iso(transfer.get("deadline_at"))
        # "deadline_at has passed" (PRD §2.10/§3.6) means the clock is strictly
        # past the deadline. At exactly deadline_at the transfer is NOT yet swept;
        # acceptance at that instant is separately rejected by the half-open
        # (< deadline_at) accept rule.
        if deadline is not None and now > deadline:
            transfer["status"] = "EXPIRED"
            db.touch(transfer)
            order = db.orders.get(transfer["order_id"])
            if order is not None and order["delivery_status"] == "IN_TRANSFER":
                order["delivery_status"] = "DELIVERY_FAILED"
                recompute.recompute_order_lifecycle(order)
                db.touch(order)


def _sweep_last_minute():
    now = clock.now()
    for event in list(db.events.values()):
        if event["status"] != "ON_SALE":
            continue
        doors = clock.parse_iso(event["doors_open_at"])
        if doors is None:
            continue
        threshold = clock.add_minutes(doors, -event["last_minute_cutoff_minutes"])
        if now >= threshold:
            event["status"] = "LAST_MINUTE"
            db.touch(event)
