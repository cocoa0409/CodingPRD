"""Auth and caller-context helpers implementing validation priorities 1-4
(PRD sections 2.1 and 2.8):

1. X-User-Role and X-User-ID headers present, role recognized -> ERR_UNAUTHENTICATED (401)
2. Role permitted on the endpoint -> ERR_UNAUTHORIZED (403)
3. (existence is checked in each handler, left-to-right, parent before child)
4. Entity-backed callers must resolve; member-scoped endpoints require ownership
   -> ERR_FORBIDDEN (403)
"""

import uuid

from flask import request

import clock
import db
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_FORBIDDEN, not_found

ROLES = ("ProgramAdmin", "Volunteer", "Member")


def authenticate(allowed_roles):
    """Priorities 1 and 2. Returns (role, user_id)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "Missing or unrecognized X-User-Role / X-User-ID headers.")
    if role not in allowed_roles:
        raise ApiError(
            ERR_UNAUTHORIZED, 403,
            "Role %s is not permitted to invoke this endpoint." % role)
    return role, user_id


def resolve_caller(role, user_id):
    """Priority 4, first half: for entity-backed roles (Volunteer, Member) the
    X-User-ID must resolve to an existing entity of the role's backing type.
    ProgramAdmin is opaque and never resolves against any entity."""
    if role == "Volunteer":
        caller = db.table("volunteers").get(user_id)
        if caller is None:
            raise ApiError(
                ERR_FORBIDDEN, 403,
                "X-User-ID does not resolve to an existing Volunteer.")
        return caller
    if role == "Member":
        caller = db.table("members").get(user_id)
        if caller is None:
            raise ApiError(
                ERR_FORBIDDEN, 403,
                "X-User-ID does not resolve to an existing Member.")
        return caller
    return None


def require_member_ownership(caller_member_id, owner_member_id):
    """Priority 4, second half: a member may only act on records that belong to
    their own membership."""
    if caller_member_id != owner_member_id:
        raise ApiError(
            ERR_FORBIDDEN, 403,
            "The acting member does not own the target resource.")


def must_find(table_name, rid, what=None):
    """Priority 3 existence check for a single identifier."""
    rec = db.table(table_name).get(rid)
    if rec is None:
        label = what or table_name.rstrip("s")
        raise not_found("%s not found: %s" % (label, rid))
    return rec


def new_common_fields():
    """id + created_at + updated_at + version for versioned entities (PRD 2.4)."""
    ts = clock.iso3(clock.now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_audit_fields():
    """id + created_at only, for the four immutable audit line types (PRD 2.4):
    ledger entries, attendance rows, screening events, treasury transactions."""
    return {
        "id": str(uuid.uuid4()),
        "created_at": clock.iso3(clock.now()),
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Every mutation increments version by exactly one and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = clock.iso3(clock.now())
