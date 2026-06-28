"""Cross-entity domain helpers: derived-field recomputation and reconciliation.

PRD §3.2 (party_size), §3.1 (portfolio_published), §3.8 (balance_reconcile).
"""
from db import store
from services.common import touch


def event_faces(event_id):
    return [f for f in store.faces.values() if f["event_id"] == event_id]


def confirmed_faces(event_id):
    return [f for f in store.faces.values()
            if f["event_id"] == event_id and f["status"] == "CONFIRMED"]


def pending_or_confirmed_faces(event_id):
    return [f for f in store.faces.values()
            if f["event_id"] == event_id and f["status"] in ("PENDING", "CONFIRMED")]


def recompute_party_size(event):
    """party_size = count of faces in PENDING or CONFIRMED (PRD §3.2)."""
    event["party_size"] = len(pending_or_confirmed_faces(event["id"]))


def recompute_portfolio_published(artist):
    """true once at least one PUBLISHED PortfolioItem exists for the artist (PRD §3.1)."""
    has_published = any(
        p for p in store.portfolio_items.values()
        if p["artist_id"] == artist["id"] and p["status"] == "PUBLISHED"
    )
    artist["portfolio_published"] = has_published


def invoice_for_event(event_id):
    for inv in store.invoices.values():
        if inv["event_id"] == event_id:
            return inv
    return None


def contract_for_invoice(invoice):
    return store.contracts.get(invoice["contract_id"])


def applied_addons_for_event(event_id):
    """Sum APPLIED add-on amounts across the event's assignments (PRD §3.8)."""
    assignment_ids = {a["id"] for a in store.assignments.values()
                      if a["event_id"] == event_id}
    return [ad for ad in store.addons.values()
            if ad["assignment_id"] in assignment_ids and ad["status"] == "APPLIED"]


def succeeded_payments(invoice_id):
    return [p for p in store.payments.values()
            if p["invoice_id"] == invoice_id and p["outcome"] == "SUCCEEDED"]


def reconcile_balance(invoice):
    """Recompute balance_amount_cents and amount_paid_cents (PRD §3.8, calc balance_reconcile).

    gross_due = contracted_total + APPLIED add-ons
    balance = max(0, gross_due - paid - relief_written_off)
    amount_paid = paid
    """
    contract = contract_for_invoice(invoice)
    contracted_total = contract["contracted_total_cents"] if contract else 0
    addons = applied_addons_for_event(invoice["event_id"])
    addons_applied = sum(ad["amount_cents"] for ad in addons)
    paid = sum(p["amount_cents"] for p in succeeded_payments(invoice["id"]))
    relief = invoice.get("_relief_written_off", 0)
    gross_due = contracted_total + addons_applied
    invoice["balance_amount_cents"] = max(0, gross_due - paid - relief)
    invoice["amount_paid_cents"] = paid


def paid_deposit(invoice_id):
    """Sum of SUCCEEDED DEPOSIT payments on the invoice."""
    return sum(p["amount_cents"] for p in store.payments.values()
               if p["invoice_id"] == invoice_id
               and p["outcome"] == "SUCCEEDED"
               and p["applies_to"] == "DEPOSIT")
