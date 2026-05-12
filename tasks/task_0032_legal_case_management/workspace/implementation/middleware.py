"""Auth/role helpers driven from PRD §2.1.

Headers: X-User-ID and X-User-Role. Role values:
  PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk, SystemIntegrator
"""

from functools import wraps

from flask import g, request

import errors


VALID_ROLES = {
    "PartnerLawyer",
    "SeniorLawyer",
    "JuniorLawyer",
    "IntakeClerk",
    "SystemIntegrator",
}

LAWYER_ROLES = {"PartnerLawyer", "SeniorLawyer", "JuniorLawyer"}


def _extract_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")

    if not user_id or not user_role:
        errors.raise_error(
            errors.ERR_AUTH_REQUIRED,
            "Missing X-User-ID or X-User-Role header.",
        )

    if user_role not in VALID_ROLES:
        errors.raise_error(
            errors.ERR_FORBIDDEN,
            f"Unknown role '{user_role}'.",
        )

    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def auth_required(*allowed_roles):
    """Decorator: ensures auth headers present, role is valid, role is allowed."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = _extract_auth()
            if user_role not in allowed:
                errors.raise_error(
                    errors.ERR_FORBIDDEN,
                    f"Role '{user_role}' is not permitted for this endpoint.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco


def get_actor():
    return getattr(g, "user_id", None), getattr(g, "user_role", None)


def acting_lawyer():
    """Return the Lawyer row backing the acting principal, or None when the
    acting role is non-lawyer (IntakeClerk, SystemIntegrator)."""
    import db
    user_id, user_role = get_actor()
    if user_role not in LAWYER_ROLES:
        return None
    return db.lawyers.get(user_id)
