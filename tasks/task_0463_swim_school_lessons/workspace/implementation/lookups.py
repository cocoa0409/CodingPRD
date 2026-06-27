"""Existence lookups raising the entity-specific not-found error. PRD 2.6 / 5."""
from db import store
from errors import (
    err,
    ERR_LOCATION_NOT_FOUND, ERR_LEVEL_NOT_FOUND, ERR_SKILL_NOT_FOUND,
    ERR_INSTRUCTOR_NOT_FOUND, ERR_PARENT_NOT_FOUND, ERR_STUDENT_NOT_FOUND,
    ERR_CLASS_SESSION_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND, ERR_INVOICE_NOT_FOUND,
    ERR_MAKEUP_CREDIT_NOT_FOUND, ERR_MAKEUP_BOOKING_NOT_FOUND, ERR_ASSESSMENT_NOT_FOUND,
)


def _get(collection, _id, error_spec):
    rec = collection.get(_id)
    if rec is None:
        err(error_spec)
    return rec


# PRD 2.6 / 2.10 / 3.3 / 3.6: a body foreign key that "points at the wrong kind of
# entity" is a REFERENCE_MISMATCH, distinct from a genuinely-missing id which is a
# NOT_FOUND. An id resolves the existence check when it names *some* persisted
# entity; only then is its type checked. This helper reports whether an id exists
# in ANY entity collection — i.e. whether the id is a real entity of some type.
def entity_exists_anywhere(_id):
    for collection in (
        store.locations, store.levels, store.skills, store.instructors,
        store.parents, store.students, store.class_sessions, store.enrollments,
        store.invoices, store.makeup_credits, store.makeup_bookings,
        store.assessments,
    ):
        if _id in collection:
            return True
    return False


def get_location(_id):
    return _get(store.locations, _id, ERR_LOCATION_NOT_FOUND)


def get_level(_id):
    return _get(store.levels, _id, ERR_LEVEL_NOT_FOUND)


def get_skill(_id):
    return _get(store.skills, _id, ERR_SKILL_NOT_FOUND)


def get_instructor(_id):
    return _get(store.instructors, _id, ERR_INSTRUCTOR_NOT_FOUND)


def get_parent(_id):
    return _get(store.parents, _id, ERR_PARENT_NOT_FOUND)


def get_student(_id):
    return _get(store.students, _id, ERR_STUDENT_NOT_FOUND)


def get_class_session(_id):
    return _get(store.class_sessions, _id, ERR_CLASS_SESSION_NOT_FOUND)


def get_enrollment(_id):
    return _get(store.enrollments, _id, ERR_ENROLLMENT_NOT_FOUND)


def get_invoice(_id):
    return _get(store.invoices, _id, ERR_INVOICE_NOT_FOUND)


def get_makeup_credit(_id):
    return _get(store.makeup_credits, _id, ERR_MAKEUP_CREDIT_NOT_FOUND)


def get_makeup_booking(_id):
    return _get(store.makeup_bookings, _id, ERR_MAKEUP_BOOKING_NOT_FOUND)


def get_assessment(_id):
    return _get(store.assessments, _id, ERR_ASSESSMENT_NOT_FOUND)
