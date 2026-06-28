"""Existence lookups (priority 3, ERR_NOT_FOUND) and ownership checks
(priority 2, ERR_FORBIDDEN_ROLE) for entity-backed roles."""
from db import db
from errors import err, ERR_NOT_FOUND, ERR_FORBIDDEN_ROLE


def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found.")
    return rec


def get_account(account_id):
    return get_or_404(db.accounts, account_id)


def get_model(model_id):
    return get_or_404(db.bike_models, model_id)


def get_rental(rental_id):
    return get_or_404(db.rentals, rental_id)


def get_bike(bike_id):
    return get_or_404(db.bikes, bike_id)


def get_ticket(ticket_id):
    return get_or_404(db.service_tickets, ticket_id)


def get_claim(claim_id):
    return get_or_404(db.coverage_claims, claim_id)


def get_offer(offer_id):
    return get_or_404(db.buyout_offers, offer_id)


def get_invoice(invoice_id):
    return get_or_404(db.fleet_invoices, invoice_id)


def get_delivery(delivery_id):
    return get_or_404(db.deliveries, delivery_id)


def get_report(report_id):
    return get_or_404(db.inspection_reports, report_id)


def check_rental_ownership(rental, user_id, role):
    """Entity-backed roles (Subscriber/FleetManager) may act on a rental only when
    its account_id == X-User-ID (PRD §2.1). Opaque roles skip ownership."""
    if role in ("Subscriber", "FleetManager"):
        if rental["account_id"] != user_id:
            raise err(ERR_FORBIDDEN_ROLE, "Caller does not own this rental.")


def check_account_ownership(account, user_id, role):
    if role in ("Subscriber", "FleetManager"):
        if account["id"] != user_id:
            raise err(ERR_FORBIDDEN_ROLE, "Caller does not own this account.")
