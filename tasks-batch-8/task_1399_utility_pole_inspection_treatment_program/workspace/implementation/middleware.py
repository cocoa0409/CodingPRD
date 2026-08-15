import functools
from flask import request

import db
from errors import ApiError

ROLES = {"ProgramManager", "Inspector", "QAReviewer", "Contractor", "AttacherRep"}

ALL_ROLES = ("ProgramManager", "Inspector", "QAReviewer", "Contractor", "AttacherRep")


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unknown X-User-Role / X-User-ID headers")
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted on this endpoint" % role)


def forbidden(msg="Forbidden"):
    raise ApiError("ERR_FORBIDDEN", 403, msg)


def locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with db.lock:
            return fn(*args, **kwargs)
    return wrapper
