from flask import request
from .errors import err

ROLES = ("Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin")


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_AUTH_REQUIRED", "Missing or invalid X-User-ID/X-User-Role")
    return uid, role


def require_role(*allowed):
    uid, role = get_auth()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", f"Role {role} not permitted")
    return uid, role
