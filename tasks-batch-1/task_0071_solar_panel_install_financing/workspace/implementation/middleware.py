from flask import request
from errors import err
from db import db

VALID_ROLES = {"Anonymous", "Homeowner", "SolarInstaller", "Utility", "SrecBroker", "PlatformAdmin"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED if headers missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header.")
    # Anonymous does not require X-User-ID
    if role != "Anonymous" and not user_id:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID header.")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", f"Role {role} not permitted for this operation.")


def authenticate(allowed_roles):
    """Run auth (401) then role check (403). Returns (user_id, role)."""
    user_id, role = get_auth()
    require_roles(role, allowed_roles)
    return user_id, role


def entity_for_role(user_id, role):
    """For entity-backed roles, return the stored entity or None."""
    if role == "Homeowner":
        return db.homeowners.get(user_id)
    if role == "SolarInstaller":
        return db.installers.get(user_id)
    if role == "Utility":
        return db.utilities.get(user_id)
    if role == "SrecBroker":
        return db.brokers.get(user_id)
    return None
