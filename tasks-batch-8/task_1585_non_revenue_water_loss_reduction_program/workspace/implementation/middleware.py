"""Auth header extraction and role checking (SCAFFOLD validations 1-2)."""

from flask import request

import errors
from errors import ApiError

ROLES = {
    "ProgramDirector",
    "UtilityAnalyst",
    "FieldSupervisor",
    "MeterTechnician",
    "Investigator",
    "RegulatorLiaison",
}


def get_actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return uid, role


def require_roles(allowed):
    uid, role = get_actor()
    if role not in allowed:
        raise ApiError(errors.ERR_UNAUTHORIZED, 403,
                       "role %s is not authorized for this operation" % role)
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
