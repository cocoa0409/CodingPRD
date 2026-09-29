"""Identity headers, RBAC and request-body plumbing (PRD 2.1)."""

import functools
import json
from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import ApiError

ROLES = (
    "ProcessEngineer",
    "HeatTreatOperator",
    "QualityInspector",
    "QualityManager",
    "ShippingClerk",
    "PlantAdmin",
)
ROLE_SET = set(ROLES)
ANY_ROLE = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def _authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED")
    return str(user_id), role


def _authorise(role, allowed):
    if role not in set(allowed):
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def _parse_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, InvalidOperation):
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def endpoint(*allowed_roles):
    """Wrap a view: authenticate, authorise, then parse the JSON body."""

    if len(allowed_roles) == 1 and isinstance(allowed_roles[0], (list, tuple, set)):
        allowed_roles = tuple(allowed_roles[0])

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = _authenticate()
            _authorise(role, allowed_roles)
            g.user_id = user_id
            g.role = role
            if request.method in ("POST", "PATCH", "PUT"):
                g.body = _parse_body()
            else:
                g.body = {}
            return view(*args, **kwargs)

        return wrapper

    return decorator
