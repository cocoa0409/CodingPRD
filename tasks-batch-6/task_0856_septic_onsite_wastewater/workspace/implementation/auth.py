"""Authentication (check 1) and role authorisation (check 2) -- PRD 2.1 / 2.6."""
from flask import request

from errors import ApiError

ROLES = (
    "Applicant",
    "DesignProfessional",
    "Installer",
    "Pumper",
    "EnvironmentalHealthSpecialist",
    "HealthOfficer",
    "RecordsClerk",
)

ALL_ROLES = list(ROLES)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Check 1 then check 2, always in that order and always before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Actor(user_id, role)
