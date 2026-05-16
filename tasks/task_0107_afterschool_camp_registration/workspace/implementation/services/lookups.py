"""Resource lookup + family-scope ownership helpers.

Existence checks raise ERR_RESOURCE_NOT_FOUND (priority 4).
Family-scope ownership checks raise ERR_FAMILY_MISMATCH (priority 5).
"""

from flask import g

from config import ROLE_GUARDIAN
from db import db
from errors import APIError


def get_family(family_id):
    fam = db.families.get(family_id)
    if not fam:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Family {family_id} not found.")
    return fam


def get_guardian(guardian_id):
    g_row = db.guardians.get(guardian_id)
    if not g_row:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Guardian {guardian_id} not found.")
    return g_row


def get_child(child_id):
    c = db.children.get(child_id)
    if not c:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Child {child_id} not found.")
    return c


def get_session(session_id):
    s = db.sessions.get(session_id)
    if not s:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Session {session_id} not found.")
    return s


def get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if not e:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Enrollment {enrollment_id} not found.")
    return e


def get_authorization(authorization_id):
    a = db.authorizations.get(authorization_id)
    if not a:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Authorization {authorization_id} not found.")
    return a


def get_scholarship(scholarship_id):
    s = db.scholarships.get(scholarship_id)
    if not s:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Scholarship {scholarship_id} not found.")
    return s


def get_session_day(session_day_id):
    sd = db.session_days.get(session_day_id)
    if not sd:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"SessionDay {session_day_id} not found.")
    return sd


def get_emergency_contact(contact_id):
    c = db.emergency_contacts.get(contact_id)
    if not c:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"EmergencyContact {contact_id} not found.")
    return c


def acting_guardian_family_id():
    """For Guardian role, return the family_id of the acting guardian. Else None."""
    if g.user_role != ROLE_GUARDIAN:
        return None
    guardian = db.guardians.get(g.user_id)
    if not guardian:
        # Guardian role but X-User-ID is not an existing guardian row
        raise APIError("ERR_FAMILY_MISMATCH", "Acting guardian record not found.")
    return guardian["family_id"]


def assert_family_scope(family_id):
    """If the caller is a Guardian, require family_id == their family. ProgramAdmin passes."""
    caller_family = acting_guardian_family_id()
    if caller_family is None:
        return
    if caller_family != family_id:
        raise APIError("ERR_FAMILY_MISMATCH")
