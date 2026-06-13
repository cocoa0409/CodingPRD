"""Route-level helpers: entity fetch-or-404, seller ownership checks.

Validation ordering (PRD §2.11): auth -> [segregation] -> existence (404,
left-to-right) -> ownership (NOT_RESOURCE_OWNER) -> state -> business rules ->
ERR_INVALID_REQUEST catch-all.
"""
from errors import err, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER
from middleware import ROLE_SELLER
from db import db


def fetch(collection, entity_id):
    """Return entity by id or raise ERR_NOT_FOUND (PRD §2.8)."""
    rec = collection.get(entity_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Referenced resource does not exist.")
    return rec


def ensure_seller_owns(role, user_id, seller_id):
    """If the caller is a Seller, enforce ownership: X-User-ID == seller_id
    (PRD §2.1). Raises ERR_NOT_RESOURCE_OWNER otherwise."""
    if role == ROLE_SELLER and user_id != seller_id:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "Seller may only act on resources they own.")
