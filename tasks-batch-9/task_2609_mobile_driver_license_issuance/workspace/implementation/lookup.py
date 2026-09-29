"""Left-to-right resource resolution (rejection-ladder steps 4 and 5)."""

from errors import ApiError
from store import db


def _get(collection, row_id, error_id):
    if not isinstance(row_id, str) or not row_id:
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def profile(row_id):
    return _get(db.interop_profiles, row_id, "ERR_INTEROP_PROFILE_NOT_FOUND")


def holder(row_id):
    return _get(db.holders, row_id, "ERR_HOLDER_NOT_FOUND")


def proofing_session(row_id):
    return _get(db.proofing_sessions, row_id, "ERR_PROOFING_SESSION_NOT_FOUND")


def device(row_id):
    return _get(db.devices, row_id, "ERR_DEVICE_NOT_FOUND")


def credential(row_id):
    return _get(db.credentials, row_id, "ERR_CREDENTIAL_NOT_FOUND")


def update_order(row_id):
    return _get(db.update_orders, row_id, "ERR_UPDATE_ORDER_NOT_FOUND")


def update_delivery(row_id):
    return _get(db.deliveries, row_id, "ERR_UPDATE_DELIVERY_NOT_FOUND")


def verifier(row_id):
    return _get(db.verifiers, row_id, "ERR_VERIFIER_NOT_FOUND")


def reader_app(row_id):
    return _get(db.reader_apps, row_id, "ERR_READER_APP_NOT_FOUND")


def presentation_session(row_id):
    return _get(db.presentation_sessions, row_id, "ERR_PRESENTATION_SESSION_NOT_FOUND")
