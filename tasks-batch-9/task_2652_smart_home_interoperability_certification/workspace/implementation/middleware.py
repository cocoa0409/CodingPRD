"""Auth header extraction, role checking, ownership (PRD 2.1, ladder rungs 1-3)."""

from flask import request

from errors import ApiError

PROGRAM_ADMIN = "ProgramAdmin"
MEMBER = "Member"
TEST_LABORATORY = "TestLaboratory"
CONFORMANCE_REVIEWER = "ConformanceReviewer"
SECURITY_REVIEWER = "SecurityReviewer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
PUBLIC_VIEWER = "PublicViewer"

ALL_ROLES = [
    PROGRAM_ADMIN,
    MEMBER,
    TEST_LABORATORY,
    CONFORMANCE_REVIEWER,
    SECURITY_REVIEWER,
    COMPLIANCE_OFFICER,
    PUBLIC_VIEWER,
]
VALID_ROLES = set(ALL_ROLES)

# Non-public read surface (PRD 4: every role except PublicViewer)
NON_PUBLIC_READ = [
    PROGRAM_ADMIN,
    MEMBER,
    TEST_LABORATORY,
    CONFORMANCE_REVIEWER,
    SECURITY_REVIEWER,
    COMPLIANCE_OFFICER,
]

SYSTEM_ACTOR = "SYSTEM"


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def auth(allowed_roles, exempt_headers=False):
    """Rung 1 then rung 2. Returns (user_id, role)."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if exempt_headers:
        # PRD 2.1: the logical-clock endpoint is exempt from header presence,
        # but role authorization still applies to any role that is supplied.
        if role is not None and role not in allowed_roles:
            raise ApiError("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
        return user_id, role
    if user_id is None or role is None or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS", "X-User-ID and a valid X-User-Role are required")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    return user_id, role


def own(user_id, owner_id):
    """Rung 3: the acting X-User-ID must be the addressed resource's owner."""
    if user_id != owner_id:
        raise ApiError("ERR_UNAUTHORIZED", "acting user does not own this resource")
