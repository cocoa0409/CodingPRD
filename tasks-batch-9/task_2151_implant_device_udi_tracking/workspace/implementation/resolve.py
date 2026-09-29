"""Ladder steps 4-5 — existence resolution, left to right / declared order."""
from errors import ApiError, NOT_FOUND_FOR
from store import db

_COLLECTION_FOR = {
    "vendor_id": "vendors",
    "agreement_id": "agreements",
    "consignment_agreement_id": "agreements",
    "catalog_item_id": "catalog_items",
    "lot_id": "lots",
    "device_unit_id": "device_units",
    "replaced_unit_id": "device_units",
    "replacement_device_unit_id": "device_units",
    "patient_id": "patients",
    "case_id": "cases",
    "surgical_case_id": "cases",
    "implant_record_id": "implant_records",
    "charge_id": "charges",
    "submission_id": "registry_submissions",
    "field_action_id": "field_actions",
    "notification_id": "recall_notifications",
    "invoice_id": "invoices",
    "explant_record_id": "explant_records",
}


def must(param, value):
    """Resolve one reference or raise that reference's own not-found code."""
    collection = getattr(db, _COLLECTION_FOR[param])
    row = collection.get(value) if isinstance(value, str) else None
    if row is None:
        raise ApiError(NOT_FOUND_FOR[param])
    return row


def maybe(param, value):
    if value is None:
        return None
    return must(param, value)
