"""Authentication, role authorization and the endpoint wrapper (PRD §2.1/§2.8)."""

from functools import wraps

from flask import g, request

from db import REQUEST_LOCK, db
from derived import effective_certification_status, reconcile
from errors import ApiError
from response import Result

ROLES = (
    "RatingProviderAdmin",
    "CertifiedRater",
    "FieldInspector",
    "QADesignee",
    "BuilderRep",
)

# Only RatingProviderAdmin has an opaque identity; the other four are entity_backed.
OPAQUE_ROLES = ("RatingProviderAdmin",)


def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or invalid.")
    if role not in OPAQUE_ROLES and not user_id:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return role, user_id


def endpoint(roles):
    """Wrap a view: auth (steps 1-2), request lock, derived reconciliation, envelope."""

    def decorator(view):
        @wraps(view)
        def wrapper(**kwargs):
            with REQUEST_LOCK:
                g.touched = set()
                g.role, g.user_id = authenticate(roles)
                result = view(**kwargs)
                if request.method != "GET":
                    reconcile()
                if not isinstance(result, Result):
                    return result
                return result.render()

        return wrapper

    return decorator


def require_owner(actual_owner_id):
    """Step 6 — ownership for the identity-bearing roles."""
    if g.role in OPAQUE_ROLES:
        return
    if actual_owner_id is None or g.user_id != actual_owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --- certification gates (steps 12-13) ------------------------------------
def check_certification_valid(rater_id):
    rater = db.raters.get(rater_id)
    if rater is None or effective_certification_status(rater) not in (
        "ACTIVE",
        "PROBATION",
    ):
        raise ApiError("ERR_CERTIFICATION_INVALID")
    return rater


def check_cert_level(rater_id, allowed_levels):
    rater = db.raters.get(rater_id)
    if rater is None or rater["cert_level"] not in allowed_levels:
        raise ApiError("ERR_CERT_LEVEL_INSUFFICIENT")
    return rater
