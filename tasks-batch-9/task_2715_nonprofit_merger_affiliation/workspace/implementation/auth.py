"""Authentication and role authorization — PRD section 2.1, ladder rules 1 and 2."""

from flask import request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "StrategyOfficer",
    "BoardSecretary",
    "DiligenceLead",
    "CharitableTrustCounsel",
    "StateCharitiesRegulator",
    "IntegrationManager",
)

ALL_ROLES = list(ROLES)

# Entity-backed roles: X-User-ID is the acting Organization's id.
ENTITY_BACKED = ("StrategyOfficer", "BoardSecretary")


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED


def _header(name):
    # Flask header lookup is already case-insensitive.
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def authenticate(allowed_roles):
    """Rule 1 then rule 2, in that order."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or role is None or role not in ROLES:
        fail(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be one "
            "of the seven declared roles.",
        )
    if role not in allowed_roles:
        fail(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorized for this endpoint." % role,
        )
    return Actor(user_id, role)
