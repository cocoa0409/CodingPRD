"""Shared route plumbing: existence resolution and paginated listing."""
import db
import response
import validation
from errors import err

NOT_FOUND = {
    "groups": "ERR_GROUP_NOT_FOUND",
    "organizers": "ERR_ORGANIZER_NOT_FOUND",
    "plans": "ERR_BUSINESS_PLAN_NOT_FOUND",
    "scenarios": "ERR_STRESS_SCENARIO_NOT_FOUND",
    "raises": "ERR_CAPITAL_RAISE_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "filings": "ERR_FILING_NOT_FOUND",
    "conditions": "ERR_CONDITION_NOT_FOUND",
    "policies": "ERR_POLICY_NOT_FOUND",
    "contracts": "ERR_VENDOR_CONTRACT_NOT_FOUND",
    "windows": "ERR_CONVERSION_WINDOW_NOT_FOUND",
    "exams": "ERR_EXAM_NOT_FOUND",
    "deviations": "ERR_DEVIATION_NOT_FOUND",
}


def must_get(collection, row_id):
    row = db.get(collection, row_id)
    if row is None:
        raise err(NOT_FOUND[collection])
    return row


def listing(collection, serializer, specs=()):
    """Paginated, `created_at`-ascending list with optional equality filters."""
    limit, offset = validation.pagination()
    rows = db.all_rows(collection)
    for field, value in specs:
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    total = len(rows)
    page = rows[offset:offset + limit]
    return response.array_response(
        [serializer(row) for row in page], limit, offset, total)
