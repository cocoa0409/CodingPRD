"""Ownership / OCC helpers shared by routes (PRD §2.1, §2.6)."""
from errors import err, ERR_UNAUTHORIZED, ERR_STALE_VERSION, ERR_INVALID_REQUEST
from middleware import (
    ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from db import db


def check_member_ownership(role, user_id, member_id):
    """A Member caller may only act on resources whose member fk == X-User-ID.
    FrontDesk has opaque identity and bypasses ownership. Instructor/Chief are
    not member-scoped here."""
    if role == ROLE_MEMBER and member_id != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only act on their own resources.")


def check_instructor_ownership(role, user_id, instructor_id):
    """An Instructor caller may only act on resources whose instructor fk ==
    X-User-ID. ChiefInstructor is a hierarchical override but is still an
    Instructor record and is scoped to its own instructor-referencing
    resources for ownership-sensitive instructor actions."""
    if role in (ROLE_INSTRUCTOR, ROLE_CHIEF) and instructor_id != user_id:
        raise err(ERR_UNAUTHORIZED, "Instructor may only act on their own resources.")


def enforce_read_ownership(role, user_id, rec, member_key="member_id",
                           instructor_key=None):
    """Ownership gate for single-resource reads/actions.

    - Member: resource's member fk must equal X-User-ID.
    - Instructor/ChiefInstructor: when the resource has an instructor fk and
      the caller is acting as an instructor, the instructor fk must equal
      X-User-ID for instructor-scoped actions (callers pass instructor_key).
    - FrontDesk: opaque, bypasses ownership.
    """
    if role == ROLE_MEMBER:
        if member_key and rec.get(member_key) != user_id:
            raise err(ERR_UNAUTHORIZED, "Member may only access their own resources.")
    if instructor_key and role in (ROLE_INSTRUCTOR, ROLE_CHIEF):
        if rec.get(instructor_key) != user_id:
            raise err(ERR_UNAUTHORIZED, "Instructor may only access their own resources.")


def require_version_field(body, field):
    """Structural-validity stage (priority 5, ERR_INVALID_REQUEST): a
    version-guarded endpoint must carry the version field as a valid integer."""
    supplied = body.get(field)
    if supplied is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}.")
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer.")
    return supplied


def check_occ(supplied, current_version):
    """OCC stage (priority 7, ERR_STALE_VERSION): supplied must equal current."""
    if supplied != current_version:
        raise err(ERR_STALE_VERSION, "version does not match current version.")
