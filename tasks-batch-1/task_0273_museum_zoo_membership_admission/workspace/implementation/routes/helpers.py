"""Shared route helpers: existence resolution + ownership checks."""
import db
from errors import not_found, not_owner


def resolve(collection, resource_id):
    """Return the record or raise ERR_NOT_FOUND (404)."""
    rec = collection.get(resource_id)
    if rec is None:
        raise not_found("Resource %s not found" % resource_id)
    return rec


def ensure_owns_membership(user_id, role, membership):
    """Patron may act only on a membership whose primary_patron_id == X-User-ID."""
    if role == "Patron" and membership["primary_patron_id"] != user_id:
        raise not_owner("Patron does not own this membership")


def ensure_owns_order(user_id, role, order):
    """Patron may act only on an order whose patron_id == X-User-ID."""
    if role == "Patron" and order["patron_id"] != user_id:
        raise not_owner("Patron does not own this order")
