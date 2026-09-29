"""Authentication, role authorization and dealer scoping (PRD 2.1)."""

from flask import g, request

from errors import ApiError

DEALER_PRINCIPAL = "DealerPrincipal"
CREDIT_OFFICER = "CreditOfficer"
CREDIT_RISK_MANAGER = "CreditRiskManager"
FIELD_AUDITOR = "FieldAuditor"
AUDIT_MANAGER = "AuditManager"
SYSTEM_OPERATOR = "SystemOperator"

ALL_ROLES = (
    DEALER_PRINCIPAL,
    CREDIT_OFFICER,
    CREDIT_RISK_MANAGER,
    FIELD_AUDITOR,
    AUDIT_MANAGER,
    SYSTEM_OPERATOR,
)


def identity():
    """Band 1 -- both headers must be present and the role must be known."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing.")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unknown.")
    g.user_id = str(user_id)
    g.user_role = role
    return g.user_id, role


def require(*roles):
    """Bands 1 and 2 -- authenticate, then check the endpoint's role list."""
    user_id, role = identity()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id, role


def is_principal():
    return getattr(g, "user_role", None) == DEALER_PRINCIPAL


def guard_dealer_id(dealer_id):
    """Band 3 -- a DealerPrincipal is entity-backed: X-User-ID is its Dealer.id."""
    if is_principal() and dealer_id != getattr(g, "user_id", None):
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "A DealerPrincipal may only act on its own dealership.",
        )


def guard_owned(record):
    """Band 3 for any resource whose reachable dealer_id must match the caller."""
    if record is not None:
        guard_dealer_id(record.get("dealer_id"))
    return record


def scope_dealer_id():
    """The dealer_id a DealerPrincipal's reads are confined to, else None."""
    if is_principal():
        return getattr(g, "user_id", None)
    return None
