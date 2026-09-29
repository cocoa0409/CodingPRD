"""Operator identity and RBAC (PRD 2.1)."""

from flask import request

from errors import ApiError

ROLE_COORDINATOR = "TransplantCoordinator"
ROLE_LIAISON = "DonorRegistryLiaison"
ROLE_DIRECTOR = "MedicalDirector"
ROLE_CENTER = "CollectionCenterOps"
ROLE_OPS = "RegistryOperations"

ROLES = (ROLE_COORDINATOR, ROLE_LIAISON, ROLE_DIRECTOR, ROLE_CENTER, ROLE_OPS)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_coordinator(self):
        return self.role == ROLE_COORDINATOR

    @property
    def is_liaison(self):
        return self.role == ROLE_LIAISON

    @property
    def is_director(self):
        return self.role == ROLE_DIRECTOR

    @property
    def is_center(self):
        return self.role == ROLE_CENTER

    @property
    def is_ops(self):
        return self.role == ROLE_OPS


def authenticate(*allowed_roles):
    """Rung 1 then rung 2 of PRD 2.9's ladder."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Actor(str(user_id).strip(), role)
