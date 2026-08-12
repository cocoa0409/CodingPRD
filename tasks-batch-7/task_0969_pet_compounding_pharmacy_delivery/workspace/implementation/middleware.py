from flask import request

from errors import ApiError

VALID_ROLES = {
    "Owner",
    "Veterinarian",
    "Pharmacist",
    "PharmacyTech",
    "ComplianceOfficer",
    "InsuranceAdjuster",
    "PharmacyAdmin",
}


def auth(*allowed_roles):
    """Authenticate via X-User-Role, then authorize against the endpoint's role set."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role header missing or does not name a declared role", 401)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "role {} is not permitted on this endpoint".format(role), 403)
    return role, request.headers.get("X-User-ID")


def require_ownership(user_id, resource_owner_id):
    if user_id != resource_owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "X-User-ID does not own the targeted resource", 403)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object", 400)
    return data
