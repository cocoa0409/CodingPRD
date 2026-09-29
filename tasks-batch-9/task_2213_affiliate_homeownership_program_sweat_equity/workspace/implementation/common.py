"""Path/body identifier resolution and list-endpoint plumbing."""
from envelope import array_response, object_response, paginate
from errors import fail
from payload import pagination
from store import db, ordered

API = "/homeownership"


def _lookup(collection, key, error_id):
    if key is None:
        return None
    row = getattr(db, collection).get(key)
    if row is None:
        fail(error_id)
    return row


def get_program(key):
    return _lookup("programs", key, "ERR_PROGRAM_NOT_FOUND")


def get_household(key):
    return _lookup("households", key, "ERR_HOUSEHOLD_NOT_FOUND")


def get_member(key):
    return _lookup("members", key, "ERR_MEMBER_NOT_FOUND")


def get_review(key):
    return _lookup("reviews", key, "ERR_REVIEW_NOT_FOUND")


def get_entry(key):
    return _lookup("entries", key, "ERR_ENTRY_NOT_FOUND")


def get_site(key):
    return _lookup("sites", key, "ERR_SITE_NOT_FOUND")


def get_shift(key):
    return _lookup("shifts", key, "ERR_SHIFT_NOT_FOUND")


def get_volunteer(key):
    return _lookup("volunteers", key, "ERR_VOLUNTEER_NOT_FOUND")


def get_assignment(key):
    return _lookup("assignments", key, "ERR_ASSIGNMENT_NOT_FOUND")


def get_enrollment(key):
    return _lookup("enrollments", key, "ERR_ENROLLMENT_NOT_FOUND")


def get_application(key):
    return _lookup("applications", key, "ERR_APPLICATION_NOT_FOUND")


def get_cost_entry(key):
    return _lookup("cost_entries", key, "ERR_ENTRY_NOT_FOUND")


def get_grant(key):
    return _lookup("grants", key, "ERR_GRANT_NOT_FOUND")


def listing(rows, projector):
    limit, offset = pagination()
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([projector(row) for row in page], limit, offset, total)


def created(data):
    return object_response(data, 201)


def okay(data):
    return object_response(data, 200)


def match(row, field, value):
    if value is None:
        return True
    return row.get(field) == value
