"""Auth header extraction and role/ownership checks (PRD §2.1, §2.8.1-2)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ROLES = {"PlantAdmin", "IntakeOperator", "LabTechnician", "PlantOperator", "Grower", "Buyer"}


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_grower(self):
        return self.role == "Grower"

    @property
    def is_buyer(self):
        return self.role == "Buyer"


def authenticate():
    """Priority 1: both headers present and role declared, else 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "Missing or invalid X-User-Role / X-User-ID headers",
        )
    return Auth(user_id, role)


def require_roles(auth, allowed):
    """Priority 2: endpoint-level role permission, else 403."""
    if auth.role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not permitted for this endpoint" % auth.role)


def forbid_unless(condition, message="Resource is outside the caller's ownership scope"):
    """Priority 2: entity-backed ownership scope, else 403."""
    if not condition:
        raise ApiError(ERR_FORBIDDEN, 403, message)


def body():
    """Parse the JSON request body leniently; missing/invalid body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data
