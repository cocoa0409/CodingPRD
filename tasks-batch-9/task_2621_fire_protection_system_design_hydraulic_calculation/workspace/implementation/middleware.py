"""Authentication, role authorisation and identity resolution.

Admission order steps 1-3 (PRD 2.8):
  1. X-User-ID and X-User-Role present and non-blank -> ERR_UNAUTHENTICATED (401)
  2. the acting role is authorised for the endpoint  -> ERR_ROLE_NOT_PERMITTED (403)
  3. for DesignEngineer / QcReviewer / AhjReviewer the X-User-ID resolves to an
     existing backing row                            -> ERR_IDENTITY_NOT_RECOGNIZED (403)
"""
from flask import request

import db
from errors import ApiError

ROLES = ["FirmAdmin", "DesignEngineer", "QcReviewer", "Contractor", "AhjReviewer"]
ALL_ROLES = list(ROLES)

# The identity-backed roles and the table that backs each of them.
ENGINEER_ROLES = ("DesignEngineer", "QcReviewer")
REVIEWER_ROLES = ("AhjReviewer",)


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_engineer(self):
        return self.role in ENGINEER_ROLES

    @property
    def is_reviewer(self):
        return self.role in REVIEWER_ROLES


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate(roles, require_user_id=True):
    role = _header("X-User-Role")
    user_id = _header("X-User-ID")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or blank.")
    if require_user_id and (user_id is None or not user_id.strip()):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or blank.")
    if role not in roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorised for this endpoint." % role,
        )
    if role in ENGINEER_ROLES:
        if user_id not in db.engineers:
            raise ApiError(
                "ERR_IDENTITY_NOT_RECOGNIZED",
                "X-User-ID does not name a registered engineer.",
            )
    elif role in REVIEWER_ROLES:
        if user_id not in db.ahj_reviewers:
            raise ApiError(
                "ERR_IDENTITY_NOT_RECOGNIZED",
                "X-User-ID does not name a registered authority reviewer.",
            )
    return Actor(role, user_id)
