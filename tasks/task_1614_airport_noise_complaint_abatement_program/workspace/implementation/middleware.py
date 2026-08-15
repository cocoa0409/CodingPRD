"""Auth header extraction and validation (PRD §2.1, validation gate 1/3/4)."""
from flask import request

from errors import err

ROLES = {
    "NoiseOfficeAdmin",
    "NoiseAnalyst",
    "CommunityLiaison",
    "StudyCoordinator",
    "BoardMember",
    "OperatorRep",
    "Complainant",
}

# Roles whose X-User-ID is an opaque identifier (never compared to entity ids).
OPAQUE_ROLES = {
    "NoiseOfficeAdmin",
    "NoiseAnalyst",
    "CommunityLiaison",
    "StudyCoordinator",
    "BoardMember",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_staff(self):
        return self.role in OPAQUE_ROLES


def get_caller():
    """Gate 1: both headers present and role declared, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "X-User-ID and a declared X-User-Role are required")
    return Caller(user_id, role)


def require_role(caller, allowed):
    """Gate 3: role appears in the endpoint's authorized role list."""
    if caller.role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE",
                  f"Role {caller.role} may not perform this operation")


def get_body():
    """Parse the JSON body; missing/non-object bodies become {}.

    A malformed JSON body on a request that declares one is a shape failure.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True, force=False)
    if data is None:
        # Could not parse; treat as validation failure.
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data
