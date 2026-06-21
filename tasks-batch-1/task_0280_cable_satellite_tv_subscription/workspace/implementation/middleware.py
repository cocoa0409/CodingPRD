"""Authentication and role-based access control (PRD §2.1, §2.7).

Auth headers (PRD §2.1):
  X-User-ID    : opaque/operator id, or — for FieldTechnician — the Technician.id,
                 or — for Subscriber — the owned Account.id
  X-User-Role  : one of exactly four role strings.

Validation precedence (PRD §2.7): authentication (401) precedes authorization
(403) precedes ownership (403) precedes existence (404) ...
"""

from flask import request

import errors

VALID_ROLES = {"BillingAdmin", "CustomerServiceAgent", "FieldTechnician", "Subscriber"}


def get_identity():
    """Extract and validate (user_id, role). Raises ERR_UNAUTHENTICATED on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Authorization check (PRD §2.7 step 2). Raises ERR_FORBIDDEN_ROLE if not allowed."""
    if role not in allowed:
        raise errors.forbidden_role()
