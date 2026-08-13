"""Auth header extraction and role checking, per PRD §2.1 and §2.6."""

from flask import request

from errors import unauthenticated, forbidden


ROLES = {"IntakeOperator", "DataSteward", "DistributionOperator", "ProviderContact"}


def get_role():
    """Return the caller role or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise unauthenticated()
    return role


def get_user_id():
    """Opaque user id; never compared to any entity id."""
    return request.headers.get("X-User-ID")


def require_roles(*allowed):
    """Validate authentication then authorization. Returns (role, user_id)."""
    role = get_role()
    if role not in allowed:
        raise forbidden()
    return role, get_user_id()


def json_body(required=True):
    """Return the parsed JSON body as a dict, or raise ERR_INVALID_REQUEST.
    An absent/empty body on POST/PATCH that expects one counts as {}."""
    from errors import invalid_request
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise invalid_request("Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def optional_json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    from errors import invalid_request
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data
