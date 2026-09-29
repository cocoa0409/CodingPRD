"""Authentication / authorization middleware (PRD 2.1, 2.6 tiers 1-2)."""
from flask import request

from constants import ALL_ROLES
from db import db
from errors import api_error

REP = "ResidentRepresentative"


def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role.strip() == "" or role not in ALL_ROLES:
        raise api_error("ERR_UNAUTHENTICATED", "X-User-Role header missing or invalid")
    if user_id is None or user_id.strip() == "":
        raise api_error("ERR_UNAUTHENTICATED", "X-User-ID header missing or empty")
    if role == REP and user_id not in db.residents:
        raise api_error(
            "ERR_UNAUTHENTICATED",
            "X-User-ID does not resolve to an existing resident",
        )
    if role not in allowed_roles:
        raise api_error("ERR_FORBIDDEN_ROLE", "Role %s is not authorized for this endpoint" % role)
    return {"user_id": user_id, "role": role}


def require_own_resident(ctx, resident_id):
    """Ownership check for a directly named resident id (path or payload)."""
    if ctx["role"] != REP:
        return
    if resident_id is None or resident_id != ctx["user_id"]:
        raise api_error("ERR_FORBIDDEN_ROLE", "A ResidentRepresentative may only address its own resident record")


def require_own_indirect(ctx, row, field="resident_id"):
    """Ownership check for a resource that names its owning resident.

    A missing row is deferred to the tier-4/5 existence check.
    """
    if ctx["role"] != REP or row is None:
        return
    if row.get(field) != ctx["user_id"]:
        raise api_error("ERR_FORBIDDEN_ROLE", "A ResidentRepresentative may only address its own resident record")


def rep_scope(ctx):
    """Implicit resident scope applied to collection reads for a representative."""
    if ctx["role"] == REP:
        return ctx["user_id"]
    return None
