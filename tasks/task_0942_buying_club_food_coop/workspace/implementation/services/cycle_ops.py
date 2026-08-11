"""The cycle lifecycle after the lock: submit, receive, consolidate, deliver,
reconcile, close and cancel."""

from datetime import timedelta

from core import clock
from core.constants import EXCEPTION_WINDOW_HOURS
from core.store import DB, ordered, touch
from services import commission, recompute, substitution
from services.lock_cascade import cancel_lines, orders_of_cycle


def void_authorizations(order):
    """Every SUCCEEDED AUTHORIZATION payment moves to VOIDED; the order's
    payment_status becomes VOIDED and authorized_amount_cents returns to 0."""
    voided = False
    for payment in ordered([p for p in DB.payments.values()
                            if p["member_order_id"] == order["id"]]):
        if payment["kind"] == "AUTHORIZATION" and payment["status"] == "SUCCEEDED":
            payment["status"] = "VOIDED"
            touch(payment)
            voided = True
    if voided:
        order["payment_status"] = "VOIDED"
        order["authorized_amount_cents"] = 0
    return voided


def submit(cycle):
    cycle["status"] = "SUBMITTED"
    for route_run in recompute.route_runs_of_cycle(cycle):
        if route_run["status"] == "QUALIFIED":
            route_run["status"] = "SUBMITTED"
            touch(route_run)
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        if drop_run["status"] == "QUALIFIED":
            drop_run["status"] = "SUBMITTED"
            touch(drop_run)
    touch(cycle)
    return cycle


def receive(cycle):
    cycle["status"] = "RECEIVED"
    cycle["received_at"] = clock.now_iso()
    cycle["exception_deadline_at"] = clock.render(
        clock.now() + timedelta(hours=EXCEPTION_WINDOW_HOURS))
    for route_run in recompute.route_runs_of_cycle(cycle):
        if route_run["status"] == "SUBMITTED":
            route_run["status"] = "RECEIVED"
            touch(route_run)
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        if drop_run["status"] == "SUBMITTED":
            drop_run["status"] = "RECEIVED"
            touch(drop_run)
    touch(cycle)
    return cycle


def pallets_of_cycle(cycle):
    out = []
    for route_run in recompute.route_runs_of_cycle(cycle):
        out.extend([p for p in DB.pallets.values()
                    if p["route_run_id"] == route_run["id"]])
    return ordered(out)


def pending_offers_of_cycle(cycle):
    out = []
    for order in orders_of_cycle(cycle):
        for line in recompute.lines_of_order(order):
            for offer in substitution.offers_for_line(line):
                if offer["status"] == "PENDING":
                    out.append(offer)
    return ordered(out)


def consolidate(cycle):
    # Silence declines.
    for offer in pending_offers_of_cycle(cycle):
        line = DB.get("OrderLine", offer["order_line_id"])
        offer["status"] = "AUTO_DECLINED"
        touch(offer)
        substitution.apply_removal(offer, line)
    cycle["status"] = "CONSOLIDATED"
    for route_run in recompute.route_runs_of_cycle(cycle):
        if route_run["status"] == "RECEIVED":
            route_run["status"] = "CONSOLIDATED"
            touch(route_run)
    touch(cycle)
    return cycle


def deliver(cycle):
    cycle["status"] = "DELIVERED"
    for pallet in pallets_of_cycle(cycle):
        if pallet["status"] == "SEALED":
            pallet["status"] = "DELIVERED"
            touch(pallet)
    for route_run in recompute.route_runs_of_cycle(cycle):
        if route_run["status"] == "CONSOLIDATED":
            route_run["status"] = "DELIVERED"
            touch(route_run)
    settled = []
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        if drop_run["status"] == "RECEIVED":
            drop_run["status"] = "SETTLED"
            touch(drop_run)
            settled.append(drop_run)
    for order in orders_of_cycle(cycle):
        if order["status"] in ("FILLED", "SHORT_FILLED"):
            order["status"] = "DELIVERED"
            touch(order)
    # One accrual per settled drop run with a coordinator, in DropRun
    # created_at ASC order.
    for drop_run in ordered(settled):
        if drop_run["coordinator_member_id"]:
            commission.accrue(drop_run)
    touch(cycle)
    return cycle


def reconcile(cycle):
    cycle["status"] = "RECONCILED"
    touch(cycle)
    return cycle


def close(cycle):
    cycle["status"] = "CLOSED"
    for order in orders_of_cycle(cycle):
        if order["status"] == "DELIVERED":
            order["status"] = "CLOSED"
            touch(order)
    touch(cycle)
    return cycle


def cancel(cycle):
    cycle["status"] = "CANCELLED"
    for route_run in recompute.route_runs_of_cycle(cycle):
        if route_run["status"] != "DEFERRED":
            route_run["status"] = "DEFERRED"
            touch(route_run)
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        if drop_run["status"] in ("OPEN", "QUALIFIED"):
            drop_run["status"] = "CANCELLED"
            touch(drop_run)
    for order in orders_of_cycle(cycle):
        if order["status"] in ("DRAFT", "SUBMITTED", "LOCKED"):
            order["status"] = "CANCELLED"
            void_authorizations(order)
            touch(order)
            cancel_lines(order, ("REQUESTED", "CONFIRMED"))
    touch(cycle)
    return cycle
