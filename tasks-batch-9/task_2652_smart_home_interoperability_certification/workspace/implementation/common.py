"""Shared route helpers: family lookups, pagination slicing."""

from db import store
from errors import ApiError

FAMILIES = {
    "specification": ("specifications", "ERR_SPECIFICATION_NOT_FOUND"),
    "feature_set": ("feature_sets", "ERR_FEATURE_SET_NOT_FOUND"),
    "member": ("members", "ERR_MEMBER_NOT_FOUND"),
    "laboratory": ("laboratories", "ERR_LABORATORY_NOT_FOUND"),
    "submission": ("submissions", "ERR_SUBMISSION_NOT_FOUND"),
    "test_plan": ("test_plans", "ERR_TEST_PLAN_NOT_FOUND"),
    "test_session": ("test_sessions", "ERR_TEST_SESSION_NOT_FOUND"),
    "plugfest": ("plugfests", "ERR_PLUGFEST_NOT_FOUND"),
    "participation": ("participations", "ERR_PARTICIPATION_NOT_FOUND"),
    "listing": ("listings", "ERR_LISTING_NOT_FOUND"),
    "case": ("cases", "ERR_CASE_NOT_FOUND"),
}


def maybe(family, row_id):
    attr, _ = FAMILIES[family]
    if not isinstance(row_id, str):
        return None
    return getattr(store, attr).get(row_id)


def must(family, row_id):
    row = maybe(family, row_id)
    if row is None:
        raise ApiError(FAMILIES[family][1], "%s %s was not found" % (family, row_id))
    return row


def body_fk(family, body, key, required=True):
    """Rung 5: resolve a body-supplied foreign key. Absent or non-string values
    are left for the rung-6 shape check."""
    if key not in body or body.get(key) is None:
        return None
    value = body.get(key)
    if not isinstance(value, str):
        return None
    return must(family, value)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
