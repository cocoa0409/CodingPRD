"""Authentication & RBAC (PRD §2.1, SCAFFOLD §1.4 priorities 1-2, §1.7)."""
from flask import request

import errors as E
from db import store

ROLES = ("AirportAdmin", "WildlifeBiologist", "ATCController", "RegulatorAgent")

ALL_ROLES = ROLES


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present, role in declared enum."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise E.ApiError(E.ERR_UNAUTHENTICATED,
                         "missing or malformed X-User-ID / X-User-Role headers", 401)
    return uid, role


def require_roles(role, allowed):
    """Priority 2: role permitted per RBAC matrix."""
    if role not in allowed:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         f"role {role} is not permitted to invoke this endpoint", 403)


def acting_biologist(uid):
    return store.biologists.get(uid)


def acting_controller(uid):
    return store.atc_controllers.get(uid)


def acting_regulator(uid):
    return store.regulators.get(uid)


def biologist_is_senior(uid):
    b = store.biologists.get(uid)
    return bool(b and b.get("is_senior"))
