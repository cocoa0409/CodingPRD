"""Authentication, RBAC, jurisdictional scope and segregation of duties (PRD §2.1)."""

from flask import request

from errors import ApiError

ROLES = (
    "StateLawAdmin",
    "MunicipalPlanner",
    "CityClerk",
    "PropertyOwner",
    "FiscalAnalyst",
    "BoundaryCommissioner",
    "CountyAssessor",
)

ANY_ROLE = ROLES

# MunicipalPlanner and CityClerk carry a Municipality id in X-User-ID.
MUNICIPAL_ROLES = ("MunicipalPlanner", "CityClerk")


def identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    return user_id, role


def prelude(allowed_roles):
    """Steps 1 and 2 of the validation ladder (PRD §2.10)."""
    user_id, role = identity()
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation." % role)
    return user_id, role


def check_municipality_scope(role, user_id, municipality_id):
    """Step 3 — skipped when the municipality cannot be determined."""
    if role in MUNICIPAL_ROLES and municipality_id is not None and user_id != municipality_id:
        raise ApiError(
            "ERR_MUNICIPALITY_SCOPE_VIOLATION",
            "The acting municipality does not own this resource.",
        )


def check_owner_scope(role, user_id, property_owner_id):
    """Step 4 — applies only to the four PropertyOwner operations."""
    if role == "PropertyOwner" and property_owner_id is not None and user_id != property_owner_id:
        raise ApiError(
            "ERR_OWNER_SCOPE_VIOLATION",
            "A property owner may only act on their own records.",
        )


def check_segregation_of_duties(user_id, case):
    """Step 5 — the commissioner may not be the analyst of record."""
    if case is not None and case.get("fiscal_finalized_by_user_id") is not None:
        if user_id == case["fiscal_finalized_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The operator who finalized the fiscal analysis may not decide the commission review.",
            )
