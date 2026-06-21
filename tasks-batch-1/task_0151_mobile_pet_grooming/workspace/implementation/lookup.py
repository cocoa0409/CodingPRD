"""Existence lookups (ERR_NOT_FOUND) and ownership helpers."""
import db
from errors import err, ERR_NOT_FOUND, ERR_FORBIDDEN


def _get(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return rec


def get_breed(rid):
    return _get(db.breeds, rid)


def get_service_tier(rid):
    return _get(db.service_tiers, rid)


def get_add_on(rid):
    return _get(db.add_ons, rid)


def get_customer(rid):
    return _get(db.customers, rid)


def get_pet(rid):
    return _get(db.pets, rid)


def get_groomer(rid):
    return _get(db.groomers, rid)


def get_van(rid):
    return _get(db.vans, rid)


def get_route_day(rid):
    return _get(db.route_days, rid)


def get_route_stop(rid):
    return _get(db.route_stops, rid)


def get_appointment(rid):
    return _get(db.appointments, rid)


def get_appointment_add_on(rid):
    return _get(db.appointment_add_ons, rid)


def get_recurring_plan(rid):
    return _get(db.recurring_plans, rid)


def get_fee_charge(rid):
    return _get(db.fee_charges, rid)


# ---------------------------------------------------------------------------
# Ownership helpers (PRD §2.1). Customer owns through Pet; Groomer owns by id.
# ---------------------------------------------------------------------------
def customer_of_pet(pet):
    return pet["customer_id"]


def customer_of_appointment(appt):
    pet = db.pets.get(appt["pet_id"])
    return pet["customer_id"] if pet else None


def customer_of_plan(plan):
    pet = db.pets.get(plan["pet_id"])
    return pet["customer_id"] if pet else None


def forbid_unless(condition):
    if not condition:
        raise err(ERR_FORBIDDEN, "Not permitted to act on this resource")
