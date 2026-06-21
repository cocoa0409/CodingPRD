from db import db
from errors import err, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER


def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return rec


def ensure_owner(role, user_id, owning_customer_id):
    """For Customer role, enforce ownership. Opaque roles pass through."""
    if role == "Customer" and user_id != owning_customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this resource")


def paginate(items, limit, offset):
    """items: list already sorted. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sorted_by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])
