"""Existence lookups (priority 4: ERR_RESOURCE_NOT_FOUND) and ownership
helpers (priority 3: ERR_NOT_RESOURCE_OWNER)."""
import errors
from db import db
from errors import err


def _get(coll, rid):
    if not isinstance(rid, str):
        return None
    return coll.get(rid)


def require_center(rid):
    rec = _get(db.centers, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Center %s not found." % rid)
    return rec


def require_program(rid):
    rec = _get(db.programs, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Program %s not found." % rid)
    return rec


def require_belt_level(rid):
    rec = _get(db.belt_levels, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "BeltLevel %s not found." % rid)
    return rec


def require_badge(rid):
    rec = _get(db.badges, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Badge %s not found." % rid)
    return rec


def require_guardian(rid):
    rec = _get(db.guardians, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Guardian %s not found." % rid)
    return rec


def require_member(rid):
    rec = _get(db.members, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Member %s not found." % rid)
    return rec


def require_membership(rid):
    rec = _get(db.memberships, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Membership %s not found." % rid)
    return rec


def require_session(rid):
    rec = _get(db.sessions, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Session %s not found." % rid)
    return rec


def require_enrollment(rid):
    rec = _get(db.enrollments, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Enrollment %s not found." % rid)
    return rec


def require_badge_award(rid):
    rec = _get(db.badge_awards, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "BadgeAward %s not found." % rid)
    return rec


def require_showcase(rid):
    rec = _get(db.showcases, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Showcase %s not found." % rid)
    return rec


def require_showcase_entry(rid):
    rec = _get(db.showcase_entries, rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "ShowcaseEntry %s not found." % rid)
    return rec


# ---- Ownership (priority 3) -------------------------------------------------

def check_owner(role, user_id, owning_guardian_id):
    """Guardian acting on a resource it does not own -> ERR_NOT_RESOURCE_OWNER.
    CenterAdmin/Instructor are never subject to ownership."""
    if role == "Guardian" and user_id != owning_guardian_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Guardian does not own this resource.")


def member_guardian_id(member):
    return member["guardian_id"]


def membership_guardian_id(membership):
    member = db.members.get(membership["member_id"])
    return member["guardian_id"] if member else None


def enrollment_guardian_id(enrollment):
    member = db.members.get(enrollment["member_id"])
    return member["guardian_id"] if member else None


def entry_guardian_id(entry):
    member = db.members.get(entry["member_id"])
    return member["guardian_id"] if member else None
