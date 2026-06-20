"""Auth header extraction and RBAC enforcement.

PRD §2.1: every request must carry `X-User-ID` and `X-User-Role`. A request
missing either, or carrying a malformed one, is rejected with
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). The four recognized roles,
spelled exactly: LoanOfficer, CreditApprover, SbaOfficer, InvestorServicer.
A valid role not permitted for the operation -> ERR_FORBIDDEN_FOR_ROLE (403).
"""
from flask import request

import errors

VALID_ROLES = {"LoanOfficer", "CreditApprover", "SbaOfficer", "InvestorServicer"}


def get_user_context():
    """Validate and return (user_id, role). Raises on missing/invalid header.

    Validation order is the §2.10 precedence:
      1. ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (header presence/well-formed)
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or role is None:
        raise errors.missing_header()
    # Malformed: empty / whitespace-only, or an unrecognized role value.
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.missing_header()
    if not isinstance(role, str) or role.strip() == "":
        raise errors.missing_header()
    if role not in VALID_ROLES:
        raise errors.missing_header()

    return user_id, role


def require_roles(role, allowed):
    """Enforce RBAC. `allowed` is an iterable of role names permitted here."""
    if role not in allowed:
        raise errors.forbidden()
