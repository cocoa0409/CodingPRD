"""Existence resolution (ERR_NOT_FOUND) and ownership checks.

Existence is validation priority 4 (PRD §2.5 / §2.9), checked left-to-right.
Ownership is priority 3 (PRD §2.1): for Guest-owned resources, X-User-ID must
equal the resource's guest_id.
"""
import errors
from db import db
from errors import ApiError


def _get(coll, rid):
    if not isinstance(rid, str) or rid not in coll:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced resource does not exist")
    return coll[rid]


def get_park(rid):
    return _get(db.parks, rid)


def get_pricing_policy(rid):
    return _get(db.pricing_policies, rid)


def get_entry_window(rid):
    return _get(db.entry_windows, rid)


def get_cabana(rid):
    return _get(db.cabanas, rid)


def get_locker(rid):
    return _get(db.lockers, rid)


def get_guest(rid):
    return _get(db.guests, rid)


def get_order(rid):
    return _get(db.orders, rid)


def get_admission(rid):
    return _get(db.admissions, rid)


def get_cabana_rental(rid):
    return _get(db.cabana_rentals, rid)


def get_locker_rental(rid):
    return _get(db.locker_rentals, rid)


def get_rain_check(rid):
    return _get(db.rain_checks, rid)


def require_owner(role, user_id, guest_id):
    """Priority 3 ownership: only enforced for the Guest role (PRD §2.1)."""
    if role == "Guest" and user_id != guest_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403,
                       "Guest may only act on their own resources")
