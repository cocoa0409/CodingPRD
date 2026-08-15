"""Auth: X-User-ID and X-User-Role headers, six declared roles, then the
per-endpoint role permission (scaffold Table 7)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = {
    "PlantAdmin",
    "SourceMonitor",
    "QAOfficer",
    "ProductionLead",
    "SanitationLead",
    "ComplianceOfficer",
}
ALL_ROLES = sorted(ROLES)


def auth(allowed_roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "missing or invalid X-User-ID / X-User-Role headers",
                    401,
                )
            if role not in allowed_roles:
                raise ApiError(
                    "ERR_FORBIDDEN",
                    f"role {role} is not permitted for this endpoint",
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
