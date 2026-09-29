"""Cascade discipline (PRD 2.10): shared unwind and recomputation helpers.

Every row a cascade mutates gets its updated_at refreshed and its version
bumped by exactly one, and every aggregate is recomputed from surviving rows
rather than adjusted blindly.  A row mutated by one logical operation is
bumped exactly once however many hops touched it, which is what the Ledger
below is for.
"""
from calc import (recompute_booking_count, recompute_clearance, recompute_showtime,
                  showtime_orders)
from store import touch
from validate import find


class Ledger:
    """Collects the rows one operation mutated so each is bumped once."""

    def __init__(self):
        self._rows = {}

    def mark(self, row):
        if row is not None:
            self._rows[id(row)] = row
        return row

    def flush(self):
        for row in self._rows.values():
            touch(row)


def _credit(member, amount):
    if member is not None and amount:
        member["credit_balance_cents"] = member["credit_balance_cents"] + amount


def order_member(order):
    return find("members", order["member_id"]) if order["member_id"] else None


def void_order(order, ledger):
    """A held order is released: comps and any consumed credit come back."""
    order["status"] = "VOID"
    ledger.mark(order)
    member = order_member(order)
    if member is not None:
        _credit(member, order["applied_credit_cents"])
        if order["applied_credit_cents"] or order["comp_quantity"]:
            ledger.mark(member)


def refund_order_cascade(order, ledger):
    """A paid order reversed by a cascade (PRD 3.2 hop four, 3.5 hop one)."""
    order["status"] = "REFUNDED"
    order["refund_destination"] = "MEMBER_CREDIT" if order["member_id"] else "CASH"
    ledger.mark(order)
    member = order_member(order)
    if member is not None:
        if order["refund_destination"] == "MEMBER_CREDIT":
            _credit(member, order["total_cents"])
        _credit(member, order["applied_credit_cents"])
        ledger.mark(member)


def void_reserved_orders(showtime, ledger):
    for order in showtime_orders(showtime["id"]):
        if order["status"] == "RESERVED":
            void_order(order, ledger)


def unwind_all_orders(showtime, ledger):
    for order in showtime_orders(showtime["id"]):
        if order["status"] == "RESERVED":
            void_order(order, ledger)
        elif order["status"] == "PAID":
            refund_order_cascade(order, ledger)


def refresh_showtime_rollup(showtime, ledger):
    if recompute_showtime(showtime):
        ledger.mark(showtime)


def refresh_clearance(clearance, ledger):
    if clearance is not None and recompute_clearance(clearance):
        ledger.mark(clearance)


def refresh_booking_count(booking, ledger):
    if booking is not None and recompute_booking_count(booking):
        ledger.mark(booking)


def cancel_showtime(showtime, cancel_reason, ledger):
    """Cancel one screening and unwind every order standing on it."""
    showtime["status"] = "CANCELLED"
    showtime["cancel_reason"] = cancel_reason
    showtime["sale_status"] = "SALES_CLOSED"
    ledger.mark(showtime)
    unwind_all_orders(showtime, ledger)
    recompute_showtime(showtime)
    refresh_clearance(find("clearances", showtime["clearance_id"]), ledger)
    refresh_booking_count(find("bookings", showtime["booking_id"]), ledger)
