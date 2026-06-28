"""Authentication and role-based authorization (PRD §2.1, §2.10 / SCAFFOLD §1.4, §1.7).

Validation ordering (global gates): auth (401) -> authorization (403) -> existence
(404) -> request body (422) -> state/business rules. This module covers the first two.
"""
from flask import request

import errors

QI_COORDINATOR = "QICoordinator"
SETTLEMENT_OFFICER = "SettlementOfficer"
EXCHANGER = "Exchanger"
VALID_ROLES = {QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER}


def require_auth():
    """Validate X-User-ID and X-User-Role headers (priority 1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) when either header is
    missing or malformed (empty, or an unrecognized role value).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Authorize the acting role against the allowed set (priority 2).

    Raises ERR_UNAUTHORIZED (403) when the role is well-formed but not permitted.
    """
    if role not in allowed:
        raise errors.unauthorized()
