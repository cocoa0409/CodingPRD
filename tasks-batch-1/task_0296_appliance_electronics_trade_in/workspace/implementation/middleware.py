"""Auth header extraction and role checking (PRD 2.1, 2.4).

Headers: X-User-ID and X-User-Role (both mandatory).
Roles: CatalogAdmin, Customer, GradingAgent, FinanceOperator.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"CatalogAdmin", "Customer", "GradingAgent", "FinanceOperator"}


def get_principal():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Authorization step 2: role must be permitted for this operation."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "role not permitted for this operation")
