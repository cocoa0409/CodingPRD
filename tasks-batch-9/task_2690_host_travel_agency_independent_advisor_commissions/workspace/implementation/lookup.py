"""Existence resolution (PRD 2.8 band 4).

Every helper raises the 404 identifier that names the missing kind, so callers
can resolve path segments strictly left to right and body foreign keys in the
order the endpoint declares them.
"""

from errors import ApiError
from store import store


def _get(bucket, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = bucket.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_advisor(row_id):
    return _get(store.advisors, row_id, "ERR_ADVISOR_NOT_FOUND")


def get_agreement(row_id):
    return _get(store.agreements, row_id, "ERR_AGREEMENT_NOT_FOUND")


def get_schedule(row_id):
    return _get(store.split_schedules, row_id, "ERR_SPLIT_SCHEDULE_NOT_FOUND")


def get_credential(row_id):
    return _get(store.credentials, row_id, "ERR_CREDENTIAL_NOT_FOUND")


def get_consortium(row_id):
    return _get(store.consortiums, row_id, "ERR_CONSORTIUM_NOT_FOUND")


def get_supplier(row_id):
    return _get(store.suppliers, row_id, "ERR_SUPPLIER_NOT_FOUND")


def get_client(row_id):
    return _get(store.clients, row_id, "ERR_CLIENT_NOT_FOUND")


def get_booking(row_id):
    return _get(store.bookings, row_id, "ERR_BOOKING_NOT_FOUND")


def get_claim(row_id):
    return _get(store.claims, row_id, "ERR_CLAIM_NOT_FOUND")


def get_run(row_id):
    return _get(store.runs, row_id, "ERR_SETTLEMENT_RUN_NOT_FOUND")


def get_statement(row_id):
    return _get(store.statements, row_id, "ERR_STATEMENT_NOT_FOUND")
