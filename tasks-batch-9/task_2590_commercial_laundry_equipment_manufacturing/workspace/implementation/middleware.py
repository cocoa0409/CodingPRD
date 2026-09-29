"""Authentication, authorization and acting-identity resolution (PRD 2.1)."""

import functools

from flask import g, request

from db import db
from errors import (ERR_DISTRIBUTOR_NOT_FOUND, ERR_TECHNICIAN_NOT_CERTIFIED,
                    ERR_TECHNICIAN_NOT_FOUND, ERR_UNAUTHENTICATED,
                    ERR_UNAUTHORIZED, fail)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PRODUCT_ENGINEER = "ProductEngineer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
PLANT_MANAGER = "PlantManager"
TRAINING_ADMINISTRATOR = "TrainingAdministrator"
CHANNEL_MANAGER = "ChannelManager"
WARRANTY_ANALYST = "WarrantyAnalyst"
TECHNICIAN = "Technician"
QUALITY_INSPECTOR = "QualityInspector"
DISTRIBUTOR = "Distributor"

ALL_ROLES = [PRODUCT_ENGINEER, COMPLIANCE_OFFICER, PLANT_MANAGER,
             TRAINING_ADMINISTRATOR, CHANNEL_MANAGER, WARRANTY_ANALYST,
             TECHNICIAN, QUALITY_INSPECTOR, DISTRIBUTOR]

OPERATOR_ROLES = [PRODUCT_ENGINEER, COMPLIANCE_OFFICER, PLANT_MANAGER,
                  TRAINING_ADMINISTRATOR, CHANNEL_MANAGER, WARRANTY_ANALYST]


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        fail(ERR_UNAUTHENTICATED,
             "Both X-User-ID and X-User-Role headers are required.")
    g.user_id = user_id
    g.role = role


def authorize(roles):
    if g.role not in ALL_ROLES or g.role not in roles:
        fail(ERR_UNAUTHORIZED,
             "Role '%s' is not authorized for this operation." % g.role)


def endpoint(roles):
    """Wrap a view with rule 1 (authentication) then rule 2 (authorization)."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def acting_technician():
    """PRD rule 22: the acting Technician / QualityInspector row must exist."""
    row = db.technicians.get(g.user_id)
    if row is None:
        fail(ERR_TECHNICIAN_NOT_FOUND,
             "The acting X-User-ID does not resolve to a stored technician.")
    return row


def acting_distributor():
    """PRD rule 22: the acting Distributor row must exist."""
    row = db.distributors.get(g.user_id)
    if row is None:
        fail(ERR_DISTRIBUTOR_NOT_FOUND,
             "The acting X-User-ID does not resolve to a stored distributor.")
    return row


def require_certified(technician, scope):
    """PRD rule 36: ACTIVE, not yet expired on the logical clock, holds the scope."""
    if technician["cert_state"] != "ACTIVE":
        fail(ERR_TECHNICIAN_NOT_CERTIFIED,
             "The technician's cert_state must be ACTIVE.")
    expires_on = technician["cert_expires_on"]
    if expires_on is None or expires_on <= db.now:
        fail(ERR_TECHNICIAN_NOT_CERTIFIED,
             "The technician's certification has lapsed.")
    if scope not in technician["cert_scopes"]:
        fail(ERR_TECHNICIAN_NOT_CERTIFIED,
             "The technician does not hold the %s scope." % scope)
