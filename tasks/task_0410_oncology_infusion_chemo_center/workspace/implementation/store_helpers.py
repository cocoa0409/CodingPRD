"""Common entity lifecycle helpers: common fields, lookups, sorting, listing."""
import itertools

import errors
from db import db, new_id, now_iso
from errors import err

# Monotonic counter to provide a stable created_at tie-break independent of
# timestamp resolution (timestamps can collide at millisecond granularity).
_seq = itertools.count(1)


def make_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(entity, bump_version=True):
    entity["updated_at"] = now_iso()
    if bump_version:
        entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip internal fields (those prefixed with _) for the response body."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


# --- Lookups (raise the resource-specific not-found error) ---

_NOT_FOUND = {
    "patients": errors.ERR_PATIENT_NOT_FOUND,
    "regimen_protocols": errors.ERR_PROTOCOL_NOT_FOUND,
    "order_set_items": errors.ERR_ORDER_SET_ITEM_NOT_FOUND,
    "chairs": errors.ERR_CHAIR_NOT_FOUND,
    "nurses": errors.ERR_NURSE_NOT_FOUND,
    "prior_authorizations": errors.ERR_PRIOR_AUTH_NOT_FOUND,
    "treatment_cycles": errors.ERR_CYCLE_NOT_FOUND,
    "drug_orders": errors.ERR_DRUG_ORDER_NOT_FOUND,
    "infusion_appointments": errors.ERR_APPOINTMENT_NOT_FOUND,
    "toxicity_events": errors.ERR_TOXICITY_EVENT_NOT_FOUND,
}


def lookup(table, entity_id):
    store = getattr(db, table)
    entity = store.get(entity_id)
    if entity is None:
        raise err(_NOT_FOUND[table], "%s not found" % table)
    return entity


def get_patient(eid):
    return lookup("patients", eid)


def get_protocol(eid):
    return lookup("regimen_protocols", eid)


def get_order_set_item(eid):
    return lookup("order_set_items", eid)


def get_chair(eid):
    return lookup("chairs", eid)


def get_nurse(eid):
    return lookup("nurses", eid)


def get_prior_auth(eid):
    return lookup("prior_authorizations", eid)


def get_cycle(eid):
    return lookup("treatment_cycles", eid)


def get_drug_order(eid):
    return lookup("drug_orders", eid)


def get_appointment(eid):
    return lookup("infusion_appointments", eid)


def get_toxicity_event(eid):
    return lookup("toxicity_events", eid)
