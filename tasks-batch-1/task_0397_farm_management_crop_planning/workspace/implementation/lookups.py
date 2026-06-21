"""Existence lookups (PRD §2.7 left-to-right reference resolution).

Each get_* returns the record or raises ERR_NOT_FOUND (404).
"""
import db
from errors import err


def _get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return rec


def parcel(_id):
    return _get(db.parcels, _id)


def crop_plan(_id):
    return _get(db.crop_plans, _id)


def input_product(_id):
    return _get(db.input_products, _id)


def input_lot(_id):
    return _get(db.input_lots, _id)


def application_record(_id):
    return _get(db.application_records, _id)


def compliance_record(_id):
    return _get(db.compliance_records, _id)


def planting_event(_id):
    return _get(db.planting_events, _id)


def harvest_event(_id):
    return _get(db.harvest_events, _id)


def harvest_lot(_id):
    return _get(db.harvest_lots, _id)


def sale_contract(_id):
    return _get(db.sale_contracts, _id)


def equipment_asset(_id):
    return _get(db.equipment_assets, _id)


def equipment_usage(_id):
    return _get(db.equipment_usages, _id)


def labor_entry(_id):
    return _get(db.labor_entries, _id)


def irrigation_event(_id):
    return _get(db.irrigation_events, _id)


def applicator(_id):
    return _get(db.applicators, _id)
