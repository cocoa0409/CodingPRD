"""Authentication, RBAC and entity-backed identity (PRD section 2.1)."""
from functools import wraps

from flask import g, request

import db
from db import store
from errors import ApiError

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

PROGRAM_ADMIN = "ProgramAdmin"
PROGRAM_AUDITOR = "ProgramAuditor"
FACILITY_ADMIN = "FacilityAdmin"
FACILITY_SCREENER = "FacilityScreener"
AUDIOLOGIST = "Audiologist"
NAVIGATOR = "Navigator"
EI_COORDINATOR = "EICoordinator"

ALL_ROLES = (
    PROGRAM_ADMIN,
    PROGRAM_AUDITOR,
    FACILITY_ADMIN,
    FACILITY_SCREENER,
    AUDIOLOGIST,
    NAVIGATOR,
    EI_COORDINATOR,
)

# Provider-backed roles and the provider_type each one must resolve to.
ROLE_PROVIDER_TYPE = {
    FACILITY_SCREENER: "SCREENER",
    AUDIOLOGIST: "AUDIOLOGIST",
    NAVIGATOR: "NAVIGATOR",
    EI_COORDINATOR: "EI_COORDINATOR",
}

# Roles whose facility scope is compared to the facility of the acted-on resource.
FACILITY_SCOPED_ROLES = (FACILITY_SCREENER, EI_COORDINATOR)


def endpoint(roles):
    """Priority 1 (auth headers) and priority 2 (role authorization)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(HEADER_USER_ID)
            role = request.headers.get(HEADER_USER_ROLE)
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def user_id():
    return g.get("user_id")


def role():
    return g.get("role")


def identity(facility_id=None):
    """Priority 7: entity-backed identity resolution and ownership.

    ProgramAdmin / ProgramAuditor identities are opaque. FacilityAdmin must be a
    Facility id; the provider-backed roles must be a Provider of the matching
    provider_type. FacilityAdmin, FacilityScreener and EICoordinator additionally
    have their facility scope compared to the facility of the acted-on resource.
    """
    caller = g.get("user_id")
    caller_role = g.get("role")
    if caller_role in (PROGRAM_ADMIN, PROGRAM_AUDITOR):
        return None
    if caller_role == FACILITY_ADMIN:
        facility = store.facilities.get(caller)
        if facility is None:
            raise ApiError("ERR_IDENTITY_MISMATCH")
        if facility_id is not None and facility_id != caller:
            raise ApiError("ERR_IDENTITY_MISMATCH")
        return facility
    expected_type = ROLE_PROVIDER_TYPE[caller_role]
    provider = store.providers.get(caller)
    if provider is None or provider["provider_type"] != expected_type:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if caller_role in FACILITY_SCOPED_ROLES and facility_id is not None:
        if provider["facility_id"] != facility_id:
            raise ApiError("ERR_IDENTITY_MISMATCH")
    return provider
