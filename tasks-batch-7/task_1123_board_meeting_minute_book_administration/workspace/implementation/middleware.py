"""Auth header extraction and role checking (PRD section 2.1).

Every request must carry non-empty X-User-ID and X-User-Role headers.
Roles: CorporateSecretary, Director, BoardChair, ExternalAuditor.
"""

from flask import g, request

from errors import ERR_FORBIDDEN_ROLE, ERR_MISSING_CONTEXT_HEADER, raise_err

ROLE_CORPORATE_SECRETARY = "CorporateSecretary"
ROLE_DIRECTOR = "Director"
ROLE_BOARD_CHAIR = "BoardChair"
ROLE_EXTERNAL_AUDITOR = "ExternalAuditor"

ALL_ROLES = (
    ROLE_CORPORATE_SECRETARY,
    ROLE_DIRECTOR,
    ROLE_BOARD_CHAIR,
    ROLE_EXTERNAL_AUDITOR,
)


def extract_context():
    """before_request hook: enforce the context-header tier (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip() or role is None or not str(role).strip():
        raise_err(
            ERR_MISSING_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Role-membership tier (priority 2)."""
    if g.role not in roles:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not admitted to this endpoint" % g.role)


def current_user_id():
    return g.user_id


def current_role():
    return g.role
