"""Auth header extraction and role checking (PRD §2.1).

Headers (authoritative names from PRD §2.1):
    X-User-ID   — calling principal identifier
    X-User-Role — one of BillingAdmin | Dispatcher | Coder | Biller | ComplianceOfficer

Validation order (PRD §3.11 / SCAFFOLD §1.4):
  priority 1 — both headers present and X-User-Role is a recognized role,
               else ERR_UNAUTHENTICATED (401)
  priority 2 — acting role permitted for the operation, else ERR_UNAUTHORIZED (403)

For entity-backed roles (Dispatcher, Coder, Biller, ComplianceOfficer) the
X-User-ID is the id of the acting AgencyStaff member. For BillingAdmin the
X-User-ID is an opaque operator identifier.
"""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, err

VALID_ROLES = {"BillingAdmin", "Dispatcher", "Coder", "Biller", "ComplianceOfficer"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the auth header pair.

    Requires both X-User-ID and X-User-Role to be present, and X-User-Role to be
    a recognized role value. Otherwise ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role header")
    return Principal(user_id, role)


def optional_authenticate():
    """For bootstrap-open endpoints: allow anonymous, but if any auth header is
    supplied it must be a valid pair.

    Returns a Principal when authenticated, or None when fully anonymous.
    If exactly one header is present, or X-User-Role is present but invalid,
    treat it as a malformed auth attempt and reject with ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None and user_id is None:
        return None
    # Some auth header present -> must be a valid pair.
    if not role or not user_id or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role header")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Raise ERR_UNAUTHORIZED unless the principal's role is in allowed_roles."""
    if principal.role not in allowed_roles:
        raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation")
