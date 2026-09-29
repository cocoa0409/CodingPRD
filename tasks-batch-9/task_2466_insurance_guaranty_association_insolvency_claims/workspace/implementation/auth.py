"""Authentication and RBAC -- PRD 2.1 and validation cascade priorities 1 and 2.

Headers: `X-User-ID` (acting principal) and `X-User-Role` (one of the eight
declared, case-sensitive role names).
"""

import functools

from flask import g, request

from errors import fail

ROLE_ASSOCIATION_ADMIN = "AssociationAdmin"
ROLE_RECEIVER_LIAISON = "ReceiverLiaison"
ROLE_COVERAGE_ANALYST = "CoverageAnalyst"
ROLE_CLAIMS_ADJUSTER = "ClaimsAdjuster"
ROLE_DEFENSE_COUNSEL = "DefenseCounsel"
ROLE_CLAIMS_COMMITTEE_OFFICER = "ClaimsCommitteeOfficer"
ROLE_ASSESSMENT_OFFICER = "AssessmentOfficer"
ROLE_MEMBER_INSURER_AGENT = "MemberInsurerAgent"

ALL_ROLES = (
    ROLE_ASSOCIATION_ADMIN,
    ROLE_RECEIVER_LIAISON,
    ROLE_COVERAGE_ANALYST,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_DEFENSE_COUNSEL,
    ROLE_CLAIMS_COMMITTEE_OFFICER,
    ROLE_ASSESSMENT_OFFICER,
    ROLE_MEMBER_INSURER_AGENT,
)

VENDOR_TYPE_FOR_ROLE = {
    ROLE_CLAIMS_ADJUSTER: "ADJUSTER",
    ROLE_DEFENSE_COUNSEL: "DEFENSE_COUNSEL",
}


def endpoint(roles):
    """Decorator running validation priorities 1 (401) and 2 (403)."""

    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role:
                fail(
                    "ERR_UNAUTHENTICATED",
                    "Both X-User-ID and X-User-Role headers are required.",
                )
            if role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a declared role." % role)
            if role not in roles:
                fail(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role '%s' is not authorised for this operation." % role,
                )
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapped

    return decorator


def acting_user_id():
    return getattr(g, "user_id", None)


def acting_role():
    return getattr(g, "role", None)
