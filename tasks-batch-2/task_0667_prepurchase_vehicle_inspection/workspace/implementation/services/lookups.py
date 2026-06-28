"""Existence lookups (ERR_NOT_FOUND, 404) — path before body per PRD §2.8."""
from db import db
from errors import err


def _get(collection, _id):
    if _id is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    obj = collection.get(_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return obj


def get_account(_id):
    return _get(db.accounts, _id)


def get_vehicle(_id):
    return _get(db.vehicles, _id)


def get_fee_schedule(_id):
    return _get(db.fee_schedules, _id)


def get_inspector(_id):
    return _get(db.inspectors, _id)


def get_order(_id):
    return _get(db.orders, _id)


def get_assignment(_id):
    return _get(db.assignments, _id)


def get_report(_id):
    return _get(db.reports, _id)


def get_photo(_id):
    return _get(db.photos, _id)


def get_vin_history_record(_id):
    return _get(db.vin_history_records, _id)


def get_vin_report(_id):
    return _get(db.vin_reports, _id)


def get_recall_record(_id):
    return _get(db.recall_records, _id)


def get_dispute(_id):
    return _get(db.disputes, _id)
