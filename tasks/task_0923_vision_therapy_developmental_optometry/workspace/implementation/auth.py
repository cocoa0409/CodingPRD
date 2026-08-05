"""Rung 1 (authentication) and rung 2 (authorization) of the §2.7 ladder."""

from flask import request

import config
from errors import ApiError
from store import db


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_patient(self):
        return self.role == config.ROLE_PATIENT


def authenticate(allowed_roles):
    """Rung 1 then rung 2.

    Rung 1: both headers present and X-User-Role is one of the seven role
    names, else ERR_UNAUTHENTICATED (401).

    Rung 2: the role appears in the endpoint's authorized-role list; for the
    three Therapist-backed roles X-User-ID must name an existing Therapist row
    and for PatientUser it must name an existing Patient row, else
    ERR_UNAUTHORIZED (403).

    NOTE (declared freedom, PRD §2.1 final paragraph): no rejection is
    specified for a caller whose named Therapist carries a `credential` other
    than the one its role implies, so none is performed here.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in config.ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")

    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")

    if role in config.THERAPIST_BACKED_ROLES:
        if user_id not in db.therapists:
            raise ApiError("ERR_UNAUTHORIZED", "X-User-ID does not name an existing Therapist row.")
    elif role == config.ROLE_PATIENT:
        if user_id not in db.patients:
            raise ApiError("ERR_UNAUTHORIZED", "X-User-ID does not name an existing Patient row.")

    return Caller(user_id, role)


def require_owner(caller, patient_id):
    """A PatientUser may act only on rows whose patient_id equals X-User-ID."""
    if caller.is_patient and patient_id != caller.user_id:
        raise ApiError("ERR_UNAUTHORIZED", "A PatientUser may only act on their own rows.")
