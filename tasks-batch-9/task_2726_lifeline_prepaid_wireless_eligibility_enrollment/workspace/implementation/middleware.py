"""Identity header extraction and role permission checks (PRD section 2.1)."""
from flask import request

from errors import ApiError

PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
PROVIDER_AGENT = "ProviderAgent"
NATIONAL_VERIFIER = "NationalVerifier"
COMPLIANCE_AUDITOR = "ComplianceAuditor"
SUBSCRIBER = "Subscriber"

ALL_ROLES = (
    PROGRAM_ADMINISTRATOR,
    PROVIDER_AGENT,
    NATIONAL_VERIFIER,
    COMPLIANCE_AUDITOR,
    SUBSCRIBER,
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_provider_agent(self):
        return self.role == PROVIDER_AGENT

    @property
    def is_subscriber(self):
        return self.role == SUBSCRIBER


def authenticate(allowed_roles):
    """Priority 10 then priority 15: headers first, then role permission.

    Runs before the body is parsed, so a request that both omits its headers
    and carries a malformed body reports the authentication failure.
    """
    user_id = request.headers.get("X-User-ID", None)
    role = request.headers.get("X-User-Role", None)
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both X-User-ID and X-User-Role headers are required")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unrecognised role '%s'" % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role '%s' is not authorized for this operation" % role)
    return Caller(user_id, role)


def require_provider_owner(caller, provider_id):
    """Peer isolation: a ProviderAgent may only act on its own carrier's rows."""
    if caller.role == PROVIDER_AGENT and caller.user_id != provider_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "ProviderAgent may only act on its own carrier's records")


def require_subscriber_owner(caller, subscriber_id):
    if caller.role == SUBSCRIBER and caller.user_id != subscriber_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Subscriber may only act on its own records")
