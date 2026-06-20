"""Authentication and RBAC (PRD §2.1, scaffold §1.7).

Auth headers (PRD §2.1): X-User-ID and X-User-Role on every protected endpoint.
- Missing header, or X-User-Role not a known role -> ERR_UNAUTHENTICATED (401).
- Well-formed but role not permitted for the operation -> ERR_FORBIDDEN_ROLE (403).

A narrow set of bootstrap operations (register a borrower, create an ABS pool,
create a rate-grid entry) are exempt from the authentication requirement, though
role authorization still governs who may call them when headers are present.
"""
from flask import request

from constants import ROLES
from errors import err

# Operation key -> set of roles permitted (PRD §4 endpoint table / scaffold §1.7).
# Keys are (METHOD, route_template).
PERMISSIONS = {
    ("POST", "/borrowers"): {"Borrower", "PlatformAdmin"},
    ("GET", "/borrowers/{id}"): {"Borrower", "PlatformAdmin", "Underwriter", "ServicingAgent"},
    ("POST", "/abs-pools"): {"PlatformAdmin"},
    ("GET", "/abs-pools/{id}"): {"PlatformAdmin", "Underwriter", "DisbursementOfficer"},
    ("POST", "/abs-pools/{id}/close"): {"PlatformAdmin"},
    ("POST", "/rate-grid-entries"): {"PlatformAdmin"},
    ("GET", "/rate-grid-entries"): {"PlatformAdmin", "Borrower", "Underwriter"},
    ("POST", "/applications"): {"Borrower"},
    ("GET", "/applications/{id}"): {"Borrower", "Underwriter", "ServicingAgent", "PlatformAdmin"},
    ("GET", "/applications"): {"Underwriter", "PlatformAdmin"},
    ("POST", "/applications/{id}/prequalify"): {"Borrower"},
    ("POST", "/applications/{id}/approve"): {"Underwriter"},
    ("POST", "/applications/{id}/decline"): {"Underwriter"},
    ("POST", "/applications/{id}/withdraw"): {"Borrower"},
    ("POST", "/applications/{id}/expire-offers"): {"PlatformAdmin"},
    ("POST", "/applications/{id}/fund"): {"DisbursementOfficer"},
    ("GET", "/offers/{id}"): {"Borrower", "Underwriter", "PlatformAdmin"},
    ("GET", "/offers"): {"Borrower", "Underwriter", "PlatformAdmin"},
    ("POST", "/offers/{id}/lock"): {"Borrower"},
    ("POST", "/cosigners"): {"Borrower"},
    ("GET", "/cosigners/{id}"): {"Borrower", "Cosigner", "Underwriter", "PlatformAdmin"},
    ("GET", "/cosigners"): {"Borrower", "Underwriter", "PlatformAdmin"},
    ("POST", "/cosigners/{id}/consent"): {"Cosigner"},
    ("POST", "/cosigners/{id}/decline"): {"Cosigner"},
    ("POST", "/cosigners/{id}/release"): {"Borrower"},
    ("GET", "/loans/{id}"): {"Borrower", "ServicingAgent", "DisbursementOfficer", "PlatformAdmin"},
    ("GET", "/loans"): {"ServicingAgent", "DisbursementOfficer", "PlatformAdmin"},
    ("POST", "/loans/{id}/payments"): {"ServicingAgent", "Borrower"},
    ("GET", "/loans/{id}/payments"): {"Borrower", "ServicingAgent", "PlatformAdmin"},
    ("POST", "/loans/{id}/forbearance"): {"ServicingAgent"},
    ("POST", "/loans/{id}/mark-delinquent"): {"ServicingAgent"},
    ("POST", "/loans/{id}/charge-off"): {"ServicingAgent"},
    ("GET", "/forbearance-plans/{id}"): {"ServicingAgent", "Borrower", "PlatformAdmin"},
    ("GET", "/forbearance-plans"): {"ServicingAgent", "Borrower", "PlatformAdmin"},
    ("POST", "/forbearance-plans/{id}/end"): {"ServicingAgent"},
    ("POST", "/disbursements"): {"DisbursementOfficer"},
    ("GET", "/disbursements/{id}"): {"DisbursementOfficer", "ServicingAgent", "PlatformAdmin"},
    ("GET", "/disbursements"): {"DisbursementOfficer", "ServicingAgent", "PlatformAdmin"},
    ("POST", "/disbursements/{id}/send"): {"DisbursementOfficer"},
    ("POST", "/disbursements/{id}/confirm"): {"DisbursementOfficer"},
    ("POST", "/disbursements/{id}/return"): {"DisbursementOfficer"},
    ("GET", "/audit-events"): {"PlatformAdmin", "Underwriter"},
    ("POST", "/_clock/set_current_utc"): {"PlatformAdmin"},
}

# Bootstrap operations exempt from the authentication requirement (PRD §2.1).
# Role authorization still applies when headers are supplied.
AUTH_EXEMPT = {
    ("POST", "/borrowers"),
    ("POST", "/abs-pools"),
    ("POST", "/rate-grid-entries"),
}


def get_identity():
    """Return (user_id, role) from the request headers (may be None)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def authorize(op_key):
    """Run authentication then role authorization for the given operation key.

    Returns (user_id, role). Raises ApiError on failure.
    Validation order (PRD §2.6): ERR_UNAUTHENTICATED -> ERR_FORBIDDEN_ROLE.
    """
    user_id, role = get_identity()
    allowed = PERMISSIONS.get(op_key, set())

    headers_present = bool(user_id) and bool(role)
    role_known = role in ROLES

    if op_key in AUTH_EXEMPT:
        # Authentication is waived for bootstrap. If headers are present we still
        # enforce role authorization; if a role is supplied it must be known.
        if role is not None and not role_known:
            raise err("ERR_UNAUTHENTICATED", "unknown role")
        if role is not None and role not in allowed:
            raise err("ERR_FORBIDDEN_ROLE", "role not permitted")
        return user_id, role

    if not headers_present or not role_known:
        raise err("ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "role not permitted for this operation")
    return user_id, role
