"""Existence resolution (checks 3 and 4) -- each collection has its own 404."""
import store
from errors import ApiError


def _get(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    record = collection.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def parcel(key):
    return _get(store.parcels, key, "ERR_PARCEL_NOT_FOUND")


def well(key):
    return _get(store.wells, key, "ERR_WELL_NOT_FOUND")


def site_evaluation(key):
    return _get(store.site_evaluations, key, "ERR_SITE_EVALUATION_NOT_FOUND")


def system_design(key):
    return _get(store.system_designs, key, "ERR_SYSTEM_DESIGN_NOT_FOUND")


def contractor(key):
    return _get(store.contractors, key, "ERR_CONTRACTOR_NOT_FOUND")


def construction_permit(key):
    return _get(store.construction_permits, key, "ERR_CONSTRUCTION_PERMIT_NOT_FOUND")


def inspection(key):
    return _get(store.inspections, key, "ERR_INSPECTION_NOT_FOUND")


def operating_permit(key):
    return _get(store.operating_permits, key, "ERR_OPERATING_PERMIT_NOT_FOUND")


def pumping_record(key):
    return _get(store.pumping_records, key, "ERR_PUMPING_RECORD_NOT_FOUND")


def repair_order(key):
    return _get(store.repair_orders, key, "ERR_REPAIR_ORDER_NOT_FOUND")


def transfer_inspection(key):
    return _get(store.transfer_inspections, key, "ERR_TRANSFER_INSPECTION_NOT_FOUND")
