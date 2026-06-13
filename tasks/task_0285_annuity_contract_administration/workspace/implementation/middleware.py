"""Authentication and role authorization (PRD §2.1, §2.9; SCAFFOLD §1.4, §1.7).

Every request must carry X-User-ID and X-User-Role. The three recognized roles
are spelled exactly: ContractAdmin, CreditingOfficer, ComplianceOfficer.
Identity is opaque — X-User-ID is never compared to a resource id for ownership;
it is only recorded on a 1035 exchange submission for the later segregation
check.
"""

from flask import request

import errors

VALID_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}


def authenticate():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_FORBIDDEN_ROLE if `role` is not in `allowed_roles`."""
    if role not in allowed_roles:
        raise errors.forbidden_role()
