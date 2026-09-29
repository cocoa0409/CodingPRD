"""Authentication / RBAC (PRD 2.1, rejection ladder rungs 1-2)."""

import functools

from flask import request

from errors import ApiError
from validation import validate_body

HEADER_USER = "X-User-ID"
HEADER_ROLE = "X-User-Role"

BREEDER_ADMIN = "BreederAdmin"
LICENSING_OFFICER = "LicensingOfficer"
PROPAGATOR = "Propagator"
TRIAL_COORDINATOR = "TrialCoordinator"
COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = (
    BREEDER_ADMIN,
    LICENSING_OFFICER,
    PROPAGATOR,
    TRIAL_COORDINATOR,
    COMPLIANCE_AUDITOR,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER)
    role = request.headers.get(HEADER_ROLE)
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Actor(user_id, role)


def endpoint(blueprint, method, rule, roles, schema=None):
    """Register a handler with the rejection ladder's first three rungs wired.

    Order: header presence -> role authorisation -> body shape. Only then does
    the handler body run (path identifiers, body FKs, ownership, OCC, state,
    business rules).
    """

    def decorator(func):
        @blueprint.route(rule, methods=[method])
        @functools.wraps(func)
        def wrapper(**path_args):
            actor = authenticate(roles)
            if schema is None:
                return func(actor, **path_args)
            body = validate_body(schema)
            return func(actor, body, **path_args)

        return wrapper

    return decorator
