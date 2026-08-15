"""Customer exposure figures, invoice creation, and credit-hold automation.

Per scaffold calculations.customer_exposure and PRD §2.9:
  outstanding_balance_cents := Σ (amount - paid) over OPEN invoices
  posted_exposure_cents     := max(0, outstanding - credit_balance)
  accrued_rental_cents      := Σ accrued_unbilled over ACTIVE/SUSPENDED agreements
  projected_exposure_cents  := posted + accrued_rental + Σ totals of
                               CONFIRMED/STAGED orders

Auto CREDIT_HOLD (NET30 only): invoice creation pushing posted strictly above
credit_limit flips ACTIVE -> CREDIT_HOLD. Auto release: payment waterfall or
invoice void bringing posted to <= limit flips CREDIT_HOLD -> ACTIVE.
"""
from datetime import timedelta

import db
from db import store, new_common, new_id, touch, iso_logical
from services import accrual


def outstanding_balance(customer_id):
    total = 0
    for inv in store.invoices.values():
        if inv["customer_id"] == customer_id and inv["status"] == "OPEN":
            total += inv["amount_cents"] - inv["paid_cents"]
    return total


def posted_exposure(cust):
    return max(0, outstanding_balance(cust["id"]) - cust["credit_balance_cents"])


def accrued_rental(customer_id):
    total = 0
    for ag in store.rental_agreements.values():
        if ag["customer_id"] == customer_id and ag["status"] in ("ACTIVE", "SUSPENDED"):
            total += accrual.accrued_unbilled(ag)
    return total


def open_order_commitment(customer_id):
    total = 0
    for o in store.orders.values():
        if o["customer_id"] == customer_id and o["fulfillment_status"] in ("CONFIRMED", "STAGED"):
            total += o["total_cents"]
    return total


def projected_exposure(cust):
    return (posted_exposure(cust)
            + accrued_rental(cust["id"])
            + open_order_commitment(cust["id"]))


def customer_view(cust):
    """Inject the computed balance family for a read."""
    out = outstanding_balance(cust["id"])
    cust["outstanding_balance_cents"] = out
    cust["posted_exposure_cents"] = max(0, out - cust["credit_balance_cents"])
    cust["accrued_rental_cents"] = accrued_rental(cust["id"])
    cust["projected_exposure_cents"] = (cust["posted_exposure_cents"]
                                        + cust["accrued_rental_cents"]
                                        + open_order_commitment(cust["id"]))
    return cust


def create_invoice(cust, source, amount_cents, order_id=None):
    """System-side invoice creation. issued_at from the logical clock; due_at is
    issued_at + 30 days for NET30 customers, equal to issued_at for CASH."""
    now = db.clock_now()
    due = now + timedelta(days=30) if cust["terms"] == "NET30" else now
    inv = {
        "id": new_id(),
        "customer_id": cust["id"],
        "source": source,
        "order_id": order_id,
        "amount_cents": amount_cents,
        "paid_cents": 0,
        "status": "OPEN",
        "issued_at": iso_logical(now),
        "due_at": iso_logical(due),
    }
    new_common(inv)
    store.invoices[inv["id"]] = inv
    return inv


def on_invoice_created(cust):
    """Hop 2/3 of the credit cascade: recompute exposure (derived on read) and
    auto-place CREDIT_HOLD when posted exposure rises strictly above the limit.
    Invoice creation is a customer-version event (PRD §2.7)."""
    touch(cust)
    if cust["terms"] == "NET30" and cust["status"] == "ACTIVE":
        if posted_exposure(cust) > cust["credit_limit_cents"]:
            cust["status"] = "CREDIT_HOLD"
            touch(cust)


def release_if_cleared(cust):
    """Auto release after a payment waterfall or invoice void: CREDIT_HOLD ->
    ACTIVE when posted exposure falls to <= credit_limit (NET30 only)."""
    if cust["terms"] == "NET30" and cust["status"] == "CREDIT_HOLD":
        if posted_exposure(cust) <= cust["credit_limit_cents"]:
            cust["status"] = "ACTIVE"
            touch(cust)
