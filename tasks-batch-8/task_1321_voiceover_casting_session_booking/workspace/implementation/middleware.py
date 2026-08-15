"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1-2)."""
from flask import request

from errors import unauthenticated, unauthorized

ROLES = [
    "CastingDirector",
    "Client",
    "Talent",
    "StudioEngineer",
    "Agent",
    "PlatformAdmin",
]

_CD = "CastingDirector"
CLIENT = "Client"
TALENT = "Talent"
ENGINEER = "StudioEngineer"
AGENT = "Agent"
ADMIN = "PlatformAdmin"


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    if allowed is not None and role not in allowed:
        raise unauthorized()
    return user_id, role


def json_body():
    """Parse the request JSON body tolerantly; empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise unauthenticated_bad_body()
    return data


def unauthenticated_bad_body():
    from errors import invalid_request
    return invalid_request("Request body must be a JSON object")
