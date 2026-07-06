"""Scheduled sweeps triggered on clock advance (PRD §2.13)."""
from __future__ import annotations
from datetime import timedelta

from db import db, bump, parse_iso
from services import order as osvc


def run_sweeps() -> None:
    _no_show_sweep()
    _event_forfeit_sweep()


def _no_show_sweep() -> None:
    """READY_FOR_PICKUP orders with pickup_deadline <= now are CANCELLED."""
    now = db.clock
    for order in list(db.orders.values()):
        if order["fulfillment_status"] != "READY_FOR_PICKUP":
            continue
        deadline_iso = order.get("pickup_deadline")
        if not deadline_iso:
            continue
        deadline = parse_iso(deadline_iso)
        if now >= deadline:
            # Release reservations
            osvc.release_reservation(order)

            # Credit customer with grand_total, flip payment_status
            if order["payment_status"] in {"DEPOSIT_HELD", "PAID"}:
                cust = db.customers.get(order["customer_id"])
                if cust is not None:
                    cust["store_credit_cents"] = int(cust.get("store_credit_cents", 0)) + int(
                        order.get("grand_total_cents", 0)
                    )
                    bump(cust)
                order["payment_status"] = "REFUNDED"

            order["fulfillment_status"] = "CANCELLED"
            bump(order)


def _event_forfeit_sweep() -> None:
    """HELD/CONFIRMED bookings where (event_date - now) < 7 days -> FORFEITED."""
    now = db.clock
    threshold = timedelta(days=7)
    for eb in list(db.event_bookings.values()):
        if eb["status"] not in {"HELD", "CONFIRMED"}:
            continue
        event_dt = parse_iso(eb["event_date"])
        if (event_dt - now) < threshold:
            eb["status"] = "FORFEITED"
            bump(eb)
