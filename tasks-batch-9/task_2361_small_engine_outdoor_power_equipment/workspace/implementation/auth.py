"""Header authentication and role authorization (PRD 2.1, ladder steps 1-2)."""

import functools

from flask import request

from errors import ApiError

ROLES = (
    "PlantAdmin",
    "CertificationEngineer",
    "ComplianceOfficer",
    "QualityEngineer",
    "ProductionPlanner",
    "ChannelPartner",
)

READ_ROLES = (
    "PlantAdmin",
    "CertificationEngineer",
    "ComplianceOfficer",
    "QualityEngineer",
    "ProductionPlanner",
)

ALL_ROLES = ROLES


def user_id():
    return request.headers.get("X-User-ID")


def user_role():
    return request.headers.get("X-User-Role")


def endpoint(roles):
    """Wrap a view so ladder steps 1 and 2 run before anything else."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "X-User-ID and a recognised X-User-Role header are required.",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE",
                    "Role %s is not permitted to invoke this operation." % role,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator
