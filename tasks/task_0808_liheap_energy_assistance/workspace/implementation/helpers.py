"""Cross-cutting route helpers: existence, ownership, serialization, listing."""
from store import db, sort_key, public
from calc import serialize_pool
from common import ApiError, list_response, parse_pagination, paginate


# --------------------------------------------------------------------------
# Serialization dispatch
# --------------------------------------------------------------------------
def serialize(collection_name, entity):
    if collection_name == "funding_pools":
        return serialize_pool(entity)
    return public(entity)


# --------------------------------------------------------------------------
# Existence (path resolution -> 404, body FK -> 422)
# --------------------------------------------------------------------------
def get_path(collection, id_, ):
    ent = collection.get(id_)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return ent


def get_ref(collection, id_):
    """Resolve a body foreign key; missing -> ERR_INVALID_REFERENCE (422)."""
    ent = collection.get(id_)
    if ent is None:
        raise ApiError("ERR_INVALID_REFERENCE", "Referenced resource does not exist")
    return ent


# --------------------------------------------------------------------------
# Ownership (§2.1) — entity-backed roles must own the target.
# --------------------------------------------------------------------------
def forbid(msg="Not permitted to act on this resource"):
    raise ApiError("ERR_FORBIDDEN", msg)


def require_household_owner(role, user_id, household_id):
    """Applicant may only act on resources whose household matches X-User-ID."""
    if role == "Applicant" and household_id != user_id:
        forbid()


def require_vendor_owner(role, user_id, vendor_id):
    """VendorAgent may only act on resources whose vendor matches X-User-ID."""
    if role == "VendorAgent" and vendor_id != user_id:
        forbid()


def household_of_application(application):
    return application["household_id"]


def household_of_income_document(doc):
    app = db.applications.get(doc["application_id"])
    return app["household_id"] if app else None


def vendor_of_payment(payment):
    pledge = db.pledges.get(payment["pledge_id"])
    return pledge["vendor_id"] if pledge else None


def vendor_of_bill_credit(credit):
    payment = db.payments.get(credit["payment_id"])
    if not payment:
        return None
    return vendor_of_payment(payment)


# --------------------------------------------------------------------------
# List + filter + paginate
# --------------------------------------------------------------------------
def list_collection(collection, collection_name, filters):
    """filters: dict of field -> expected value (skip None). Returns a Flask response."""
    limit, offset = parse_pagination()
    items = list(collection.values())
    for field, expected in filters.items():
        if expected is not None:
            items = [e for e in items if e.get(field) == expected]
    items.sort(key=sort_key)
    page, total = paginate(items, limit, offset)
    data = [serialize(collection_name, e) for e in page]
    return list_response(data, limit, offset, total)
