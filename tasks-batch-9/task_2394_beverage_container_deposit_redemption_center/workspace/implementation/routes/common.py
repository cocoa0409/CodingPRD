"""Shared lookup and guard helpers used by the route modules."""
import db
import response
import validation
from errors import fail

NOT_FOUND = {
    "distributor": "ERR_DISTRIBUTOR_NOT_FOUND",
    "product": "ERR_PRODUCT_NOT_FOUND",
    "center": "ERR_CENTER_NOT_FOUND",
    "machine": "ERR_MACHINE_NOT_FOUND",
    "account": "ERR_ACCOUNT_NOT_FOUND",
    "visit": "ERR_VISIT_NOT_FOUND",
    "bag_drop": "ERR_BAG_DROP_NOT_FOUND",
    "batch": "ERR_BATCH_NOT_FOUND",
    "retailer": "ERR_RETAILER_NOT_FOUND",
    "period": "ERR_PERIOD_NOT_FOUND",
}

STORES = {
    "distributor": db.distributors,
    "product": db.products,
    "center": db.centers,
    "machine": db.machines,
    "account": db.accounts,
    "visit": db.visits,
    "bag_drop": db.bag_drops,
    "batch": db.batches,
    "retailer": db.retailers,
    "period": db.periods,
}


def lookup(kind, resource_id):
    """Resolve a stored row or raise the kind's 404."""
    store = STORES[kind]
    rec = store.get(resource_id) if isinstance(resource_id, str) else None
    if rec is None:
        fail(NOT_FOUND[kind], "No %s with that identifier." % kind.replace("_", " "))
    return rec


def fk(kind, body, field, required=False):
    """Rung 6: resolve a foreign key supplied in the request body."""
    if field not in body or body[field] is None:
        if required:
            return None
        return None
    value = body[field]
    if not isinstance(value, str):
        return None
    return lookup(kind, value)


def require_operational(center):
    if center is not None and center["status"] != "OPERATIONAL":
        fail("ERR_CENTER_NOT_OPERATIONAL", "The redemption centre is not OPERATIONAL.")


def require_obligated(retailer):
    if retailer is not None and retailer["obligation_status"] != "OBLIGATED":
        fail("ERR_RETAILER_EXEMPT", "The retailer is exempt from the obligation.")


def check_account_standing(account, blocked_when_flagged=True):
    """Rung 21."""
    if account is None:
        return
    if account["status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "The redeemer account is closed.")
    if blocked_when_flagged and account["status"] == "FLAGGED":
        fail("ERR_ACCOUNT_FLAGGED", "The redeemer account is flagged.")


def check_version(supplied, record, error_id):
    """Rungs 2.6 / ladder rung 10."""
    if supplied != record["version"]:
        fail(error_id, "The supplied expected version does not match the stored version.")


def unique(store, field, value, error_id):
    """Rung 31."""
    for rec in store.values():
        if rec.get(field) == value:
            fail(error_id, "The value of '%s' is already in use." % field)


def listing(rows, serializer=db.public):
    limit, offset = validation.paginate()
    total = len(rows)
    page = validation.slice_rows(rows, limit, offset)
    return response.collection([serializer(r) for r in page], limit, offset, total)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
