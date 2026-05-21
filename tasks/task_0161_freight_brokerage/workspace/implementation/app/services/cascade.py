"""Cascading side-effects: settlement/load lifecycle, recourse, safety score.

These helpers are called from the route handlers when a state transition
needs to propagate beyond the immediate target.
"""

from __future__ import annotations

from typing import Optional

from .calc import (
    SAFETY_SUSPEND_THRESHOLD,
    safety_penalty,
)
from ..store import store


def recompute_invoice_balance(invoice: dict) -> None:
    """``balance_due_cents = max(0, invoice_total - amount_paid - amount_credited)``."""
    total = int(invoice.get("invoice_total_cents", 0))
    paid = int(invoice.get("amount_paid_cents", 0))
    credited = int(invoice.get("amount_credited_cents", 0))
    balance = total - paid - credited
    if balance < 0:
        balance = 0
    invoice["balance_due_cents"] = balance


def maybe_auto_settle(invoice: dict) -> None:
    """If balance is zero and not FACTORED, advance settlement to PAID."""
    if invoice.get("settlement_status") != "ISSUED":
        return
    if int(invoice.get("balance_due_cents", 0)) != 0:
        return
    if invoice.get("factoring_status") == "FACTORED":
        # Per PRD §3.10 the auto-PAID rule fires only when factoring_status is
        # not FACTORED.  RECOURSED is *not* FACTORED, so it counts.
        return

    invoice["settlement_status"] = "PAID"
    # Cascade: drop shipper outstanding by original frozen invoice total,
    # snapshotted at issuance and stored on the invoice as
    # ``original_invoice_total_cents`` (see invoices.py /invoice creation).
    shipper = store.shippers.get(invoice.get("shipper_id"))
    if shipper is not None:
        original_total = int(invoice.get("original_invoice_total_cents", invoice.get("invoice_total_cents", 0)))
        new_outstanding = int(shipper.get("outstanding_invoiced_cents", 0)) - original_total
        if new_outstanding < 0:
            new_outstanding = 0
        shipper["outstanding_invoiced_cents"] = new_outstanding
        store.bump(shipper)

    # And the underlying load advances to SETTLED.
    load = store.loads.get(invoice.get("load_id"))
    if load is not None and load.get("status") == "INVOICED":
        load["status"] = "SETTLED"
        store.bump(load)


def auto_suspend_carrier_if_unsafe(carrier: dict) -> None:
    """If safety_score drops below the suspend threshold while QUALIFIED, suspend."""
    if carrier.get("status") != "QUALIFIED":
        return
    if int(carrier.get("safety_score", 0)) < SAFETY_SUSPEND_THRESHOLD:
        carrier["status"] = "SUSPENDED"
        store.bump(carrier)


def apply_resolved_dispute(claim: dict, *, settled_credit: int) -> None:
    """Apply the full cascade for a DisputeClaim → RESOLVED transition.

    Mutates Invoice, possibly FactoringAdvance, and the underlying Carrier in
    place.  The caller is responsible for setting ``claim['status']`` to
    ``'RESOLVED'`` and ``claim['settled_credit_cents']`` before invoking this.
    """
    invoice = store.invoices.get(claim["invoice_id"])
    if invoice is None:
        return

    c = int(settled_credit)

    # Apply credit to invoice
    invoice["amount_credited_cents"] = int(invoice.get("amount_credited_cents", 0)) + c
    invoice["invoice_total_cents"] = int(invoice.get("invoice_total_cents", 0)) - c
    recompute_invoice_balance(invoice)

    # FACTORED + non-zero credit → RECOURSED cascade
    if invoice.get("factoring_status") == "FACTORED" and c > 0:
        invoice["factoring_status"] = "RECOURSED"
        advance = _find_advance_for_invoice(invoice["id"])
        if advance is not None:
            advance["recourse_owed_cents"] = c
        # The brokerage is buying back the receivable to the credit extent
        invoice["amount_paid_cents"] = int(invoice.get("amount_paid_cents", 0)) - c
        if int(invoice.get("amount_paid_cents", 0)) < 0:
            invoice["amount_paid_cents"] = 0
        recompute_invoice_balance(invoice)

    # Carrier safety-score penalty (only when credit > 0)
    if c > 0:
        load = store.loads.get(invoice.get("load_id"))
        if load is not None:
            carrier = store.carriers.get(load.get("carrier_id"))
            shipper = store.shippers.get(invoice.get("shipper_id"))
            if carrier is not None and shipper is not None:
                penalty = safety_penalty(
                    claim_type=claim["claim_type"],
                    smartway_required=bool(shipper.get("smartway_required", False)),
                    smartway_certified=bool(carrier.get("smartway_certified", False)),
                )
                new_score = int(carrier.get("safety_score", 0)) - penalty
                if new_score < 0:
                    new_score = 0
                carrier["safety_score"] = new_score
                store.bump(carrier)
                auto_suspend_carrier_if_unsafe(carrier)

    # Possible auto-settle
    maybe_auto_settle(invoice)


def _find_advance_for_invoice(invoice_id: str) -> Optional[dict]:
    for fa in store.factoring_advances.values():
        if fa.get("invoice_id") == invoice_id:
            return fa
    return None
