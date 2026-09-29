"""Authentication and role authorisation (PRD §2.1, rejection ranks 1 and 2)."""

from flask import request

from errors import ApiError

ROLES = (
    "LeagueDataOps",
    "CalibrationEngineer",
    "Statistician",
    "QualityReviewer",
    "ClubDataOfficer",
    "Licensee",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(*allowed_roles):
    """Rank 1 then rank 2 of the rejection ladder (PRD §2.10)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both X-User-ID and X-User-Role headers are required and the role "
            "must be one of the six declared roles.",
        )
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not permitted on this operation." % role,
        )
    return Principal(user_id, role)
