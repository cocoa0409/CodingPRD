"""Existence lookups returning the entity or raising ERR_NOT_FOUND (PRD §2.7)."""
import db
import errors


def _get(collection, _id):
    if not isinstance(_id, str):
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    ent = collection.get(_id)
    if ent is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return ent


def customer(_id):
    return _get(db.customers, _id)


def technician(_id):
    return _get(db.technicians, _id)


def door_model(_id):
    return _get(db.door_models, _id)


def opener_model(_id):
    return _get(db.opener_models, _id)


def part(_id):
    return _get(db.parts, _id)


def equipment_unit(_id):
    return _get(db.equipment_units, _id)


def quote(_id):
    return _get(db.quotes, _id)


def quote_line(_id):
    return _get(db.quote_lines, _id)


def job(_id):
    return _get(db.jobs, _id)


def part_reservation(_id):
    return _get(db.part_reservations, _id)


def warranty_plan(_id):
    return _get(db.warranty_plans, _id)


def financing_application(_id):
    return _get(db.financing_applications, _id)


def callback(_id):
    return _get(db.callbacks, _id)
