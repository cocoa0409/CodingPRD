"""Auth header extraction, role checking, and ArtistPortal ownership checks."""

from flask import request

from errors import raise_err

ROLES = {"LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"}

ALL_ROLES = ["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"]
STAFF_ROLES = ["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager"]


def auth(roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role membership.

    Returns (user_id, role).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "Missing or unknown X-User-ID / X-User-Role header",
        )
    if role not in roles:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Caller role not authorized for this endpoint")
    return uid, role


def check_ownership(role, uid, owning_artist_id):
    """ArtistPortal callers: X-User-ID must equal the owning Artist.id."""
    if role == "ArtistPortal" and uid != owning_artist_id:
        raise_err(
            "ERR_ARTIST_OWNERSHIP_MISMATCH",
            "ArtistPortal caller does not own the addressed resource",
        )
