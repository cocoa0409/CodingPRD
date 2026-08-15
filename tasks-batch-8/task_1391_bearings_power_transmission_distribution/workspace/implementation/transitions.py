"""Scheduled transitions fired by logical-clock advancement (PRD §2.4):
price files PENDING->EFFECTIVE, contracts ACTIVE->EXPIRED, reservations
ACTIVE->EXPIRED, approved returns APPROVED->EXPIRED. Due transitions fire in
due-instant order, created_at ASC within the same instant."""

from datetime import timedelta

import domain
from db import store
from helpers import touch, now
from domain import RMA_WINDOW_DAYS


def _apply_price_file_effective(pf):
    pf["status"] = "EFFECTIVE"
    pf["_took_effect"] = True
    touch(pf)
    product = store.products[pf["product_id"]]
    # any other EFFECTIVE file of this product becomes SUPERSEDED
    for other in store.price_files.values():
        if (
            other["id"] != pf["id"]
            and other["product_id"] == pf["product_id"]
            and other["status"] == "EFFECTIVE"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    product["list_price_cents"] = pf["new_list_price_cents"]
    product["last_price_change_at"] = pf["effective_at"]
    touch(product)


def _apply_reservation_expired(res):
    res["status"] = "EXPIRED"
    touch(res)
    # hop 2: line STOCK_RESERVED -> PENDING_SOURCING
    line = store.order_lines.get(res["order_line_id"])
    if line and line["sourcing_status"] == "STOCK_RESERVED":
        line["sourcing_status"] = "PENDING_SOURCING"
        touch(line)
        # hop 3: order fulfillment re-evaluated (FULLY_SOURCED -> CONFIRMED)
        order = store.orders.get(line["order_id"])
        if order:
            domain.reevaluate_order_fulfillment(order)


def run_scheduled_transitions():
    """Fire every due scheduled transition given the current logical clock."""
    current = now()
    due = []
    for pf in store.price_files.values():
        if pf["status"] == "PENDING" and pf["effective_at"] <= current:
            due.append((pf["effective_at"], pf["created_at"], pf["_seq"], "price_file", pf["id"]))
    for c in store.contracts.values():
        if c["status"] == "ACTIVE" and c["effective_to"] <= current:
            due.append((c["effective_to"], c["created_at"], c["_seq"], "contract", c["id"]))
    for r in store.reservations.values():
        if r["status"] == "ACTIVE" and current > r["expires_at"]:
            due.append((r["expires_at"], r["created_at"], r["_seq"], "reservation", r["id"]))
    for ra in store.returns.values():
        if ra["status"] == "APPROVED" and ra["approved_at"] is not None:
            lapse = ra["approved_at"] + timedelta(days=RMA_WINDOW_DAYS)
            if current > lapse:
                due.append((lapse, ra["created_at"], ra["_seq"], "return", ra["id"]))
    due.sort(key=lambda item: (item[0], item[1], item[2]))

    for _, _, _, kind, rid in due:
        if kind == "price_file":
            pf = store.price_files[rid]
            if pf["status"] == "PENDING":
                _apply_price_file_effective(pf)
        elif kind == "contract":
            c = store.contracts[rid]
            if c["status"] == "ACTIVE" and c["effective_to"] <= current:
                c["status"] = "EXPIRED"
                touch(c)
        elif kind == "reservation":
            r = store.reservations[rid]
            if r["status"] == "ACTIVE":
                _apply_reservation_expired(r)
        elif kind == "return":
            ra = store.returns[rid]
            if ra["status"] == "APPROVED":
                ra["status"] = "EXPIRED"
                touch(ra)
