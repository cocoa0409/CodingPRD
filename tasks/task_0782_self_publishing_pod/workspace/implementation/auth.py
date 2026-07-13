"""Authentication, RBAC and ownership resolution (PRD §2.1)."""
from flask import request

from envelope import ApiError
from store import db

ROLES = {"Publisher", "Reviewer", "PlatformAdmin"}


def identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED (401) when headers are
    missing or the role is unknown. This is the highest-precedence check."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """403 when the acting role is not permitted for the endpoint."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this operation")


# ---- ownership resolution: owning publisher_id of each entity ----

def _format_owner(fmt):
    if fmt is None:
        return None
    title = db.titles.get(fmt.get("title_id"))
    return title.get("publisher_id") if title else None


def owner_of(entity_kind, rec):
    if rec is None:
        return None
    if entity_kind == "publisher":
        return rec["id"]
    if entity_kind == "title":
        return rec.get("publisher_id")
    if entity_kind == "format":
        return _format_owner(rec)
    if entity_kind == "isbn":
        return rec.get("publisher_id")
    if entity_kind == "statement":
        return rec.get("publisher_id")
    if entity_kind in ("asset", "price", "proof", "drequest", "salesline"):
        fmt = db.formats.get(rec.get("format_id"))
        return _format_owner(fmt)
    return None


def require_ownership(role, user_id, entity_kind, rec):
    """For a Publisher acting on / reading an owned resource, the owning
    publisher_id must equal X-User-ID, else 403. Non-Publisher roles skip."""
    if role != "Publisher":
        return
    if owner_of(entity_kind, rec) != user_id:
        raise ApiError("ERR_FORBIDDEN", "Publisher does not own the target resource")
