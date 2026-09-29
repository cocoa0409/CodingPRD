"""Authentication and role authorization (PRD sections 2.1 and 2.7 ranks 1-2)."""

import functools

from flask import g, request

import errors
from errors import fail

ROLE_SPECIALIST = "RegulatoryAffairsSpecialist"
ROLE_REVIEWER = "SubstantiationReviewer"
ROLE_APPROVAL = "ClaimApprovalOfficer"
ROLE_QA = "QualityAssuranceManager"
ROLE_SUPPLIER_REP = "SupplierRepresentative"
ROLE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = (
    ROLE_SPECIALIST,
    ROLE_REVIEWER,
    ROLE_APPROVAL,
    ROLE_QA,
    ROLE_SUPPLIER_REP,
    ROLE_AUDITOR,
)


def endpoint(roles):
    """Decorator running screen 1 (authentication) then screen 2 (authorization).

    Both headers must be present and non-empty and X-User-Role must name one of
    the six declared roles, otherwise ERR_UNAUTHENTICATED.  This is the first
    check performed on any request, before the URL is resolved to a resource.
    """
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or user_id == "" or role is None or role == "":
                fail(errors.ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role are required.")
            if role not in ALL_ROLES:
                fail(errors.ERR_UNAUTHENTICATED, "X-User-Role names an unknown role.")
            g.user_id = user_id
            g.role = role
            if role not in allowed:
                fail(
                    errors.ERR_UNAUTHORIZED,
                    "Role %s is not authorized for this operation." % role,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return g.user_id


def role():
    return g.role
