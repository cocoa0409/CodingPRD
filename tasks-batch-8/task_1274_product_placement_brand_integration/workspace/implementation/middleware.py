"""Auth header extraction and role checking per PRD 2.1."""
from flask import request

import errors

ROLES = [
    "AgencyAdmin",
    "BrandRep",
    "IntegrationManager",
    "ProductionRep",
    "NetworkStandardsReviewer",
    "ClearanceOfficer",
    "VerificationAnalyst",
]

ALL_ROLES = list(ROLES)


def actor():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Authenticate and enforce endpoint role authorization."""
    user_id, role = actor()
    if role not in allowed:
        raise errors.unauthorized_role()
    return user_id, role


def get_json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise errors.invalid_request("Request body must be valid JSON")
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body
