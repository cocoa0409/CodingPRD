"""Authentication / authorization (PRD 2.1, validation cascade priorities 1-2).

Headers: X-User-ID (identity) and X-User-Role (capacity). Roles:
Customer (entity-backed: X-User-ID is the Customer id), MarginAnalyst,
MarginSupervisor, LiquidationDesk, MarketDataOps (opaque identifiers).
"""
from flask import request

from errors import missing_context, insufficient_permissions, ownership_mismatch

CUSTOMER = "Customer"
ANALYST = "MarginAnalyst"
SUPERVISOR = "MarginSupervisor"
DESK = "LiquidationDesk"
MARKET_OPS = "MarketDataOps"

ROLES = (CUSTOMER, ANALYST, SUPERVISOR, DESK, MARKET_OPS)
ANY_ROLE = list(ROLES)


def authenticate():
    """Priority 1: both headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise missing_context()
    return uid, role


def require_roles(role_list):
    """Priorities 1-2: user context, then endpoint role membership."""
    uid, role = authenticate()
    if role not in role_list:
        raise insufficient_permissions()
    return uid, role


def check_customer_ownership(uid, owner_customer_id):
    """Priority 4: customer-scoped writes require X-User-ID == owning Customer id."""
    if uid != owner_customer_id:
        raise ownership_mismatch()
