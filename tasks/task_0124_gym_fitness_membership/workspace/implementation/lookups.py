"""Existence lookups (PRD §2.10 priority 3: ERR_NOT_FOUND, left-to-right).

A plan that is archived is still a valid existing entity for reads; archival
only blocks new member registration (handled separately by ERR_PLAN_ARCHIVED).
"""
import db
import errors


def _get(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


def get_plan(_id):
    return _get(db.store.membership_plans, _id)


def get_location(_id):
    return _get(db.store.locations, _id)


def get_member(_id):
    return _get(db.store.members, _id)


def get_class_session(_id):
    return _get(db.store.class_sessions, _id)


def get_booking(_id):
    return _get(db.store.bookings, _id)


def get_pt_package(_id):
    return _get(db.store.pt_packages, _id)


def get_pt_session(_id):
    return _get(db.store.pt_sessions, _id)


def get_dues_invoice(_id):
    return _get(db.store.dues_invoices, _id)


def get_guest_pass(_id):
    return _get(db.store.guest_passes, _id)


def get_check_in(_id):
    return _get(db.store.check_ins, _id)
