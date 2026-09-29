"""Reference resolution and not-found reporting (PRD section 2.5)."""

from errors import (
    ERR_ACQUIRER_NOT_FOUND,
    ERR_AUDIT_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_FX_RATE_NOT_FOUND,
    ERR_INCENTIVE_PROGRAM_NOT_FOUND,
    ERR_MCC_DEFINITION_NOT_FOUND,
    ERR_MERCHANT_NOT_FOUND,
    ERR_PLATFORM_NOT_FOUND,
    ERR_RATE_PROGRAM_NOT_FOUND,
    ERR_RATE_VERSION_NOT_FOUND,
    ERR_RECLASS_REQUEST_NOT_FOUND,
    ERR_RECORD_NOT_FOUND,
    ERR_WINDOW_NOT_FOUND,
    fail,
)
from store import store


def _get(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id)
    return row


def platform(row_id):
    return _get(store.platforms, row_id, ERR_PLATFORM_NOT_FOUND)


def acquirer(row_id):
    return _get(store.acquirers, row_id, ERR_ACQUIRER_NOT_FOUND)


def mcc_definition(row_id):
    return _get(store.mcc_definitions, row_id, ERR_MCC_DEFINITION_NOT_FOUND)


def merchant(row_id):
    return _get(store.merchants, row_id, ERR_MERCHANT_NOT_FOUND)


def rate_program(row_id):
    return _get(store.rate_programs, row_id, ERR_RATE_PROGRAM_NOT_FOUND)


def rate_version(row_id):
    return _get(store.rate_versions, row_id, ERR_RATE_VERSION_NOT_FOUND)


def window(row_id):
    return _get(store.windows, row_id, ERR_WINDOW_NOT_FOUND)


def batch(row_id):
    return _get(store.batches, row_id, ERR_BATCH_NOT_FOUND)


def record(row_id):
    return _get(store.records, row_id, ERR_RECORD_NOT_FOUND)


def reclass_request(row_id):
    return _get(store.reclass_requests, row_id, ERR_RECLASS_REQUEST_NOT_FOUND)


def incentive_program(row_id):
    return _get(store.incentive_programs, row_id, ERR_INCENTIVE_PROGRAM_NOT_FOUND)


def enrollment(row_id):
    return _get(store.enrollments, row_id, ERR_ENROLLMENT_NOT_FOUND)


def audit(row_id):
    return _get(store.audits, row_id, ERR_AUDIT_NOT_FOUND)


def fx_rate(row_id):
    return _get(store.fx_rates, row_id, ERR_FX_RATE_NOT_FOUND)
