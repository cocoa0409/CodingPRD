"""Auth header extraction, RBAC and ApplicantAgent ownership scope.

Ladder rungs 1-3 of PRD 2.7 live here.
"""
from flask import request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "ApplicantAgent",
    "ProgramSpecialist",
    "GrantsOfficer",
    "AppealsAdjudicator",
    "StateAuditor",
)

ALL_ROLES = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_agent(self):
        return self.role == "ApplicantAgent"


def authenticate(allowed_roles):
    """Rung 1 (401) then rung 2 (403)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is not None:
        user_id = user_id.strip()
    if role is not None:
        role = role.strip()
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "authentication headers missing or invalid")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "role %s may not perform this operation" % role)
    return Actor(user_id, role)


def check_scope(actor, applicant_id):
    """Rung 3 (403). No-op for non-agents and for unresolvable owners."""
    if not actor.is_agent:
        return
    if applicant_id is None:
        return
    if applicant_id != actor.user_id:
        fail(
            "ERR_APPLICANT_SCOPE_VIOLATION",
            "resource does not roll up to the acting applicant",
        )
