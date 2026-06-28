"""Existence lookups (priority 4, ERR_NOT_FOUND) and ownership checks
(priority 3, ERR_NOT_RESOURCE_OWNER) for the entity-backed BoatOwner role."""
from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_SOURCE_NOT_FOUND,
)


def get_or_404(collection, _id):
    if not isinstance(_id, str):
        raise err(ERR_NOT_FOUND, "Resource not found.")
    rec = collection.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found.")
    return rec


def get_marina(_id):
    return get_or_404(db.marinas, _id)


def get_forklift(_id):
    return get_or_404(db.forklifts, _id)


def get_rack(_id):
    return get_or_404(db.racks, _id)


def get_vessel(_id):
    return get_or_404(db.vessels, _id)


def get_owner(_id):
    return get_or_404(db.owners, _id)


def get_policy(_id):
    return get_or_404(db.policies, _id)


def get_agreement(_id):
    return get_or_404(db.agreements, _id)


def get_waitlist_entry(_id):
    return get_or_404(db.waitlist, _id)


def get_launch(_id):
    return get_or_404(db.launches, _id)


def get_slot(_id):
    return get_or_404(db.slots, _id)


def get_service_order(_id):
    return get_or_404(db.service_orders, _id)


def get_invoice(_id):
    return get_or_404(db.invoices, _id)


def resolve_polymorphic_source(source_kind, source_id):
    """Priority 5: source_id must resolve to a row of the exact declared type
    (ERR_SOURCE_NOT_FOUND, 404)."""
    coll = {
        "STORAGE_AGREEMENT": db.agreements,
        "LAUNCH_REQUEST": db.launches,
        "SERVICE_ORDER": db.service_orders,
    }.get(source_kind)
    if coll is None:
        return None
    rec = coll.get(source_id) if isinstance(source_id, str) else None
    if rec is None:
        raise err(ERR_SOURCE_NOT_FOUND, "Polymorphic source not found for declared source_kind.")
    return rec


# ---- BoatOwner ownership chain (PRD §2.1, priority 3 / ERR_NOT_RESOURCE_OWNER) ----

def owner_id_of_vessel(vessel):
    return vessel["owner_id"]


def check_vessel_owner(vessel, user_id, role):
    if role == "BoatOwner" and vessel["owner_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Caller does not own this resource.")


def check_owner_account(owner, user_id, role):
    if role == "BoatOwner" and owner["id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Caller does not own this resource.")
