"""Shared route plumbing: transaction wrapper, lookups and posture guards."""

import functools

import config
import db
import payload
import response
from errors import ApiError
from services import derive, uow


def transactional(fn):
    """Run a mutating handler, reconcile derived state, then serialize."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        uow.begin()
        out = fn(*args, **kwargs)
        uow.finalize()
        if out is None:
            return response.object_response({}, 200)
        kind, row, status = out
        data = {} if kind is None else derive.serialize(kind, row)
        return response.object_response(data, status)

    return wrapper


def read_one(kind, row):
    return response.object_response(derive.serialize(kind, row), 200)


def read_many(kind, rows):
    page, meta = payload.paginate(rows)
    return response.list_response(derive.serialize_many(kind, page), meta, 200)


# ------------------------------------------------------------------- lookups

NOT_FOUND = {
    "affiliations": "ERR_AFFILIATION_NOT_FOUND",
    "practices": "ERR_PRACTICE_NOT_FOUND",
    "doctors": "ERR_DOCTOR_NOT_FOUND",
    "conversion_vendors": "ERR_CONVERSION_VENDOR_NOT_FOUND",
    "doctor_employments": "ERR_DOCTOR_EMPLOYMENT_NOT_FOUND",
    "service_agreements": "ERR_SERVICE_AGREEMENT_NOT_FOUND",
    "migration_batches": "ERR_MIGRATION_BATCH_NOT_FOUND",
    "payer_contracts": "ERR_PAYER_CONTRACT_NOT_FOUND",
    "payer_enrollments": "ERR_PAYER_ENROLLMENT_NOT_FOUND",
    "earnout_tranches": "ERR_EARNOUT_TRANCHE_NOT_FOUND",
    "supply_preference_exceptions": "ERR_SUPPLY_EXCEPTION_NOT_FOUND",
    "vendor_consolidations": "ERR_VENDOR_CONSOLIDATION_NOT_FOUND",
    "clinical_quality_reviews": "ERR_QUALITY_REVIEW_NOT_FOUND",
}


def load(kind, row_id):
    """Gauntlet position 4: path-parameter existence."""
    row = db.get(kind, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def load_fk(data, key, kind):
    """Gauntlet position 5: body foreign-key existence.

    Returns None when the key is absent or unusable, leaving the payload-shape
    check at position 6 to report it.
    """
    value = payload.fk(data, key)
    if value is None:
        return None
    row = db.get(kind, value)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


# -------------------------------------------------------------------- guards


def require_affiliated(practice):
    """Gauntlet position 17."""
    if practice["affiliation_status"] != "AFFILIATED":
        raise ApiError(
            "ERR_PRACTICE_NOT_AFFILIATED",
            "The practice has not been affiliated yet.",
        )


def require_posture(practice, allowed):
    """Gauntlet position 18."""
    if derive.integration_posture(practice) not in allowed:
        raise ApiError(
            "ERR_PRACTICE_POSTURE_BLOCKED",
            "The practice integration posture blocks this operation.",
        )


def require_occ_affiliation(affiliation, expected):
    """Gauntlet position 7."""
    if expected is not None and expected != affiliation["version"]:
        raise ApiError("ERR_STALE_AFFILIATION_VERSION")


def require_occ_practice(practice, expected):
    """Gauntlet position 8."""
    if expected is not None and expected != practice["version"]:
        raise ApiError("ERR_STALE_PRACTICE_VERSION")


def filter_rows(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


def filter_posture(rows, value):
    if value is None:
        return rows
    return [row for row in rows if derive.integration_posture(row) == value]
