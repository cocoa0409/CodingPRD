"""Auth middleware. Headers X-User-ID and X-User-Role are mandatory; an
unknown role string is unauthenticated. Endpoint role lists are enforced per
the RBAC matrix. X-User-ID identities are opaque."""

from functools import wraps

from flask import request, g

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = (
    "ContractorAdmin",
    "SiteSupervisor",
    "Surveyor",
    "AbatementSupervisor",
    "ClearanceOfficer",
    "UtilityCoordinator",
    "PermitCoordinator",
    "AuthorityReviewer",
    "StructuralEngineer",
    "PeerReviewEngineer",
    "SalvageEstimator",
    "EnvironmentalMonitor",
    "HaulingDispatcher",
    "MunicipalInspector",
)
ROLE_SET = frozenset(ROLES)
ALL_ROLES = ROLES


def require_roles(*allowed):
    allowed_set = frozenset(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not role or role not in ROLE_SET or not uid:
                raise err(ERR_UNAUTHENTICATED,
                          "Missing/unknown X-User-Role or missing X-User-ID")
            if role not in allowed_set:
                raise err(ERR_FORBIDDEN, "Role not permitted on this endpoint")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def body():
    """JSON request body as a dict; absent body becomes {} (field validation
    then reports ERR_VALIDATION for required fields)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data
