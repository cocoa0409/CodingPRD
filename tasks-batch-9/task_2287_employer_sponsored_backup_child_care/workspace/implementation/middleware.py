"""Auth header extraction and role / scope checking (PRD §2.1, §2.8 bands 1-2)."""

from flask import request

from db import db
from errors import ApiError
from util import ROLES, require_object


def json_body():
    """Parse the JSON request body; a malformed or non-object body is a band-1 fault."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST")
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return require_object(parsed)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "" or role.strip() not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id.strip(), role.strip()


def auth(*allowed_roles):
    """Band 2: authenticate, then check the endpoint's role list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def caller_employee(user_id):
    for row in db.employees.values():
        if row["user_id"] == user_id:
            return row
    return None


def assert_employee_scope(user_id, role, employee_id):
    """employee_user may only touch its own Employee row (validation 220)."""
    if role != "employee_user":
        return
    own = caller_employee(user_id)
    if own is None or employee_id is None or own["id"] != employee_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE")


def assert_provider_scope(user_id, role, provider_id):
    """provider_manager may only act on providers it owns (validation 230)."""
    if role != "provider_manager":
        return
    if provider_id is None:
        raise ApiError("ERR_FORBIDDEN_SCOPE")
    provider = db.providers.get(provider_id)
    if provider is None or provider["owner_user_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE")
