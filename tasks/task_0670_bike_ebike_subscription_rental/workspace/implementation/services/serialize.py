"""Public serialization of entities. Strips internal fields (those prefixed
with '_') and injects freshly computed derived fields."""
from services.reconcile import outstanding_balance


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def bike_model_view(model):
    return _public(model)


def account_view(account):
    out = _public(account)
    out["outstanding_balance_cents"] = outstanding_balance(account["id"])
    return out


def rental_view(rental):
    return _public(rental)


def delivery_view(delivery):
    return _public(delivery)


def service_ticket_view(ticket):
    return _public(ticket)


def inspection_report_view(report):
    return _public(report)


def coverage_claim_view(claim):
    return _public(claim)


def buyout_offer_view(offer):
    return _public(offer)


def fleet_invoice_view(invoice):
    return _public(invoice)


def bike_view(bike):
    return _public(bike)
