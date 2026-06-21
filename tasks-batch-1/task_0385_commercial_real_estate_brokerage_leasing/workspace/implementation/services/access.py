"""FK resolution and ownership/party checks (PRD §2.1, §2.5, §2.10)."""
from db import db
from errors import err


def resolve(store, rid):
    """Return the record or raise ERR_NOT_FOUND (PRD §2.5)."""
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def resolve_fk(store, rid):
    """Resolve a body FK; None/missing or unresolved -> ERR_NOT_FOUND."""
    if rid is None:
        raise err("ERR_NOT_FOUND", "Referenced resource not found")
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource not found")
    return rec


# ---------------------------------------------------------------------------
# Ownership checks (PRD §2.1). Raise ERR_NOT_OWNER on mismatch.
# ---------------------------------------------------------------------------
def owns_property(user_id, prop):
    if prop["listing_broker_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker does not own this property")


def owns_space(user_id, space):
    prop = db.properties.get(space["property_id"])
    if prop is None or prop["listing_broker_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker does not own this space")


def owns_listing(user_id, listing):
    if listing["listing_broker_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker does not own this listing")


def owns_requirement(user_id, req):
    if req["tenant_broker_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker does not own this requirement")


def owns_tour(user_id, tour):
    if tour["tenant_broker_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker does not own this tour")


def is_deal_listing_party(user_id, deal):
    return deal["listing_broker_id"] == user_id


def is_deal_procuring_party(user_id, deal):
    return deal["procuring_broker_id"] == user_id


def deal_party(user_id, role, deal):
    """A party broker of the deal (PRD §2.1). Raises ERR_NOT_OWNER otherwise.

    ListingBroker must match listing_broker_id; TenantBroker must match
    procuring_broker_id.
    """
    if role == "ListingBroker" and is_deal_listing_party(user_id, deal):
        return
    if role == "TenantBroker" and is_deal_procuring_party(user_id, deal):
        return
    raise err("ERR_NOT_OWNER", "Acting broker is not a party to this deal")
