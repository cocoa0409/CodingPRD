"""Path and body reference resolution (rungs 4 and 5)."""

from db import db
from errors import ApiError


def _resolve(collection, identifier, error_id):
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id, "%s does not resolve to a live row." % identifier)
    return row


def owner(identifier):
    return _resolve(db.owners, identifier, "ERR_OWNER_NOT_FOUND")


def territory(identifier):
    return _resolve(db.territories, identifier, "ERR_TERRITORY_NOT_FOUND")


def inspector(identifier):
    return _resolve(db.inspectors, identifier, "ERR_INSPECTOR_NOT_FOUND")


def application(identifier):
    return _resolve(db.applications, identifier, "ERR_APPLICATION_NOT_FOUND")


def registration(identifier):
    return _resolve(db.registrations, identifier, "ERR_REGISTRATION_NOT_FOUND")


def claim(identifier):
    return _resolve(db.claims, identifier, "ERR_CLAIM_NOT_FOUND")


def order(identifier):
    return _resolve(db.orders, identifier, "ERR_ORDER_NOT_FOUND")


def lot(identifier):
    return _resolve(db.lots, identifier, "ERR_LOT_NOT_FOUND")


def bill_of_sale(identifier):
    return _resolve(db.bills, identifier, "ERR_BILL_OF_SALE_NOT_FOUND")


def estray_case(identifier):
    return _resolve(db.estrays, identifier, "ERR_ESTRAY_CASE_NOT_FOUND")


def investigation(identifier):
    return _resolve(db.investigations, identifier, "ERR_INVESTIGATION_NOT_FOUND")


def remittance(identifier):
    return _resolve(db.remittances, identifier, "ERR_REMITTANCE_NOT_FOUND")


def filtered(collection, filters):
    """Apply simple equality filters supplied on the query string."""
    rows = list(collection.values())
    for field, value in filters.items():
        if value is None:
            continue
        rows = [row for row in rows if row.get(field) == value]
    return rows
