"""Shared lookup, filter and listing helpers for the route modules."""

from db import db, serialize, sorted_rows
from errors import ApiError
from response import listing
from validators import pagination


def _lookup(table, row_id, error_id, label):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "%s %s was not found" % (label, row_id))
    return row


def get_licensee(row_id):
    return _lookup(db.licensees, row_id, "ERR_LICENSEE_NOT_FOUND", "Licensee")


def get_jurisdiction(row_id):
    return _lookup(db.jurisdictions, row_id, "ERR_JURISDICTION_NOT_FOUND", "Jurisdiction")


def get_control_person(row_id):
    return _lookup(db.control_persons, row_id, "ERR_CONTROL_PERSON_NOT_FOUND", "Control person")


def get_application(row_id):
    return _lookup(db.applications, row_id, "ERR_APPLICATION_NOT_FOUND", "Application")


def get_license(row_id):
    return _lookup(db.state_licenses, row_id, "ERR_LICENSE_NOT_FOUND", "State license")


def get_delegate(row_id):
    return _lookup(db.delegates, row_id, "ERR_DELEGATE_NOT_FOUND", "Delegate")


def get_authorization(row_id):
    return _lookup(db.authorizations, row_id, "ERR_AUTHORIZATION_NOT_FOUND", "Authorization")


def get_holding(row_id):
    return _lookup(db.holdings, row_id, "ERR_HOLDING_NOT_FOUND", "Investment holding")


def get_test(row_id):
    return _lookup(db.tests, row_id, "ERR_TEST_NOT_FOUND", "Coverage test")


def get_exam(row_id):
    return _lookup(db.exams, row_id, "ERR_EXAM_NOT_FOUND", "Examination")


def get_info_request(row_id):
    return _lookup(db.info_requests, row_id, "ERR_INFO_REQUEST_NOT_FOUND", "Information request")


def get_enforcement(row_id):
    return _lookup(db.enforcements, row_id, "ERR_ENFORCEMENT_NOT_FOUND", "Enforcement action")


def paginate(rows, limit=None, offset=None):
    """Sorted by created_at ascending, then windowed and serialized."""
    if limit is None or offset is None:
        limit, offset = pagination()
    ordered = sorted_rows(rows)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return listing([serialize(r) for r in window], limit, offset, total)


def filter_rows(rows, filters):
    """filters: {field_name: expected_value_or_None}."""
    out = list(rows)
    for field, expected in filters.items():
        if expected is None:
            continue
        out = [r for r in out if r.get(field) == expected]
    return out
