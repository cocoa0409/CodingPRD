"""Shared entity helpers."""
import uuid

from db import db
from errors import raise_err


def new_id():
    return str(uuid.uuid4())


def now():
    return db.logical_now


def touch(entity):
    """Stamp updated_at and bump version for a mutation."""
    entity["updated_at"] = db.logical_now
    entity["version"] += 1


def new_entity():
    """Base fields for a fresh entity."""
    ts = db.logical_now
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


# --- not-found lookup helpers ---
def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise_err("ERR_CUSTOMER_NOT_FOUND", "customer id does not exist")
    return c


def get_staff(sid):
    s = db.staff.get(sid)
    if s is None:
        raise_err("ERR_STAFF_NOT_FOUND", "staff id does not exist")
    return s


def get_bay(bid):
    b = db.bays.get(bid)
    if b is None:
        raise_err("ERR_BAY_NOT_FOUND", "bay id does not exist")
    return b


def get_session(sid):
    s = db.fitting_sessions.get(sid)
    if s is None:
        raise_err("ERR_SESSION_NOT_FOUND", "fitting session id does not exist")
    return s


def get_package(pid):
    p = db.lesson_packages.get(pid)
    if p is None:
        raise_err("ERR_PACKAGE_NOT_FOUND", "lesson package id does not exist")
    return p


def get_spec(sid):
    s = db.build_specs.get(sid)
    if s is None:
        raise_err("ERR_SPEC_NOT_FOUND", "build spec id does not exist")
    return s


def get_component_item(iid):
    i = db.component_items.get(iid)
    if i is None:
        raise_err("ERR_COMPONENT_ITEM_NOT_FOUND", "component item id does not exist")
    return i


def get_order(oid):
    o = db.component_orders.get(oid)
    if o is None:
        raise_err("ERR_ORDER_NOT_FOUND", "component order id does not exist")
    return o


def get_ticket(tid):
    t = db.repair_tickets.get(tid)
    if t is None:
        raise_err("ERR_TICKET_NOT_FOUND", "repair ticket id does not exist")
    return t


def get_appraisal(aid):
    a = db.trade_in_appraisals.get(aid)
    if a is None:
        raise_err("ERR_APPRAISAL_NOT_FOUND", "trade-in appraisal id does not exist")
    return a


def get_listing(lid):
    l = db.used_club_listings.get(lid)
    if l is None:
        raise_err("ERR_LISTING_NOT_FOUND", "used club listing id does not exist")
    return l


def get_claim(cid):
    c = db.warranty_claims.get(cid)
    if c is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "warranty claim id does not exist")
    return c


def check_ownership(entity, user_id, role):
    """For Customer actors on owned resources: X-User-ID must match the owner id.

    Owned resources carry a customer_id field; a Customer entity itself is
    identified by its id.
    """
    if role != "Customer":
        return
    owner_id = entity.get("customer_id", entity.get("id"))
    if owner_id != user_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "actor does not own this resource")


def check_create_ownership(body_customer_id, user_id, role):
    """On create endpoints, a Customer caller's body customer_id must equal X-User-ID."""
    if role == "Customer" and body_customer_id != user_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "cannot create a resource for another customer")


def append_ledger_entry(customer_id, amount_cents, reason, reference_id):
    entry = {
        "id": new_id(),
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "reason": reason,
        "reference_id": reference_id,
        "created_at": db.logical_now,
    }
    db.credit_ledger_entries.append(entry)
    return entry
