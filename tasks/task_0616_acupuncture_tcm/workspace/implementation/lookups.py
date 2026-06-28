"""Existence lookups (priority 4/5) with the correct not-found error_id each."""

from db import db
from errors import err

# Map collection -> not-found error_id (PRD 2.8 / Section 5).
_NOT_FOUND = {
    "patients": "ERR_PATIENT_NOT_FOUND",
    "intakes": "ERR_INTAKE_NOT_FOUND",
    "treatment_plans": "ERR_PLAN_NOT_FOUND",
    "package_series": "ERR_PACKAGE_NOT_FOUND",
    "appointments": "ERR_APPT_NOT_FOUND",
    "dispenses": "ERR_DISPENSE_NOT_FOUND",
    "practitioners": "ERR_PRACTITIONER_NOT_FOUND",
    "rooms": "ERR_ROOM_NOT_FOUND",
    "herbal_formulas": "ERR_FORMULA_NOT_FOUND",
    "herb_items": "ERR_HERB_NOT_FOUND",
}

# AddOn / Charge / Superbill are not part of the declared not-found vocabulary
# (PRD Section 5). A missing GET-by-id on them yields a generic 404.
from errors import ApiError


def get_or_404(collection_name, rid):
    coll = getattr(db, collection_name)
    rec = coll.get(rid)
    if rec is None:
        error_id = _NOT_FOUND.get(collection_name)
        if error_id is None:
            raise ApiError("ERR_NOT_FOUND", 404, f"{collection_name} id not found.")
        raise err(error_id, f"{collection_name} id not found.")
    return rec


def get_patient(rid):
    return get_or_404("patients", rid)


def get_intake(rid):
    return get_or_404("intakes", rid)


def get_plan(rid):
    return get_or_404("treatment_plans", rid)


def get_package(rid):
    return get_or_404("package_series", rid)


def get_appointment(rid):
    return get_or_404("appointments", rid)


def get_dispense(rid):
    return get_or_404("dispenses", rid)


def get_practitioner(rid):
    return get_or_404("practitioners", rid)


def get_room(rid):
    return get_or_404("rooms", rid)


def get_formula(rid):
    return get_or_404("herbal_formulas", rid)


def get_herb(rid):
    return get_or_404("herb_items", rid)
