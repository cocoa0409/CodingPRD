"""Authentication, RBAC, ownership, agency scope and segregation of duties.

Admission order (PRD 2.8): headers -> role known -> role permitted ->
cardholder ownership -> agency scope -> segregation of duties.
"""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("Cardholder", "AgencySupplier", "ProgramAdmin", "ProgramApprover", "FraudAnalyst")

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate(allowed_roles, method, path):
    user_id = _header(HEADER_USER_ID)
    role = _header(HEADER_USER_ROLE)
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_AUTH_HEADERS",
            "Both X-User-Role and X-User-ID are required.",
        )
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role '%s' may not call %s %s." % (role, method, path),
        )
    g.user_id = user_id
    g.role = role


def endpoint(roles):
    """Decorator applying the auth ladder for one endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles, request.method, request.path)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def caller_id():
    return getattr(g, "user_id", None)


def caller_role():
    return getattr(g, "role", None)


def require_ownership(account_id):
    """Cardholder ownership: the acting X-User-ID must equal the account_id."""
    if caller_role() != "Cardholder":
        return
    if account_id is None:
        return
    if account_id != caller_id():
        raise ApiError(
            "ERR_ACCOUNT_OWNERSHIP_REQUIRED",
            "Cardholder '%s' may only act on their own account." % caller_id(),
        )


def require_agency_scope(agency_partner_id):
    """AgencySupplier scope: the acting X-User-ID must equal the agency id."""
    if caller_role() != "AgencySupplier":
        return
    if agency_partner_id is None:
        return
    if agency_partner_id != caller_id():
        raise ApiError(
            "ERR_AGENCY_SCOPE_VIOLATION",
            "Agency '%s' may not act on inventory of agency '%s'."
            % (caller_id(), agency_partner_id),
        )


def require_sod(other_user_id):
    """Segregation of duties: the acting operator may not be the opposing one."""
    if other_user_id is not None and other_user_id == caller_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "Operator '%s' may not perform both halves of this control." % caller_id(),
        )
