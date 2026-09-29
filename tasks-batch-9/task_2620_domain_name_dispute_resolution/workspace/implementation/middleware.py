"""Authentication header extraction and role gating."""

from flask import request

from errors import ApiError

ROLES = (
    "ProviderAdmin",
    "CaseManager",
    "Complainant",
    "Respondent",
    "Panelist",
    "RegistrarAgent",
)


def auth(*allowed_roles):
    """Band 1 then band 2 of the order of refusal.

    Every request carries X-User-ID and X-User-Role.  A missing, blank or
    unrecognised pair is ERR_UNAUTHENTICATED; a well-formed identity whose role
    is not permitted on the route is ERR_UNAUTHORIZED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def body():
    """The parsed JSON object, or an empty mapping when there is no usable body."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload
