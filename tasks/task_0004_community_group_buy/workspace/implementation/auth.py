"""Auth header parsing and role/ownership enforcement (PRD §2.1)."""
from flask import request, g

from errors import (
    APIError,
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN,
    ERR_OWNERSHIP_VIOLATION,
)
from store import store


VALID_ROLES = {"PlatformAdmin", "GroupLeader", "Customer", "Supplier", "PickupOperator", "CustomerService"}
ENTITY_BACKED = {"GroupLeader", "Customer", "Supplier"}


def parse_auth():
    """Header presence + role recognition + entity resolution.

    Sets g.user_id, g.role. Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    if role not in VALID_ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    # Entity resolution for entity-backed roles -> ERR_FORBIDDEN if unknown
    if role == "GroupLeader" and user_id not in store.group_leaders:
        raise_err(ERR_FORBIDDEN)
    if role == "Customer" and user_id not in store.customers:
        raise_err(ERR_FORBIDDEN)
    if role == "Supplier" and user_id not in store.suppliers:
        raise_err(ERR_FORBIDDEN)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_role(*allowed_roles):
    """Role-endpoint permission check (priority 3)."""
    if g.role not in allowed_roles:
        raise_err(ERR_FORBIDDEN)


def is_in_subtree(root_leader_id, leader_id):
    """True if leader_id == root or leader_id descends from root via parent_leader_id chain."""
    if leader_id == root_leader_id:
        return True
    cur = store.group_leaders.get(leader_id)
    while cur and cur.get("parent_leader_id"):
        if cur["parent_leader_id"] == root_leader_id:
            return True
        cur = store.group_leaders.get(cur["parent_leader_id"])
    return False


def own_customer(customer_id):
    if g.role == "Customer" and g.user_id != customer_id:
        raise_err(ERR_OWNERSHIP_VIOLATION)


def own_supplier(supplier_id):
    if g.role == "Supplier" and g.user_id != supplier_id:
        raise_err(ERR_OWNERSHIP_VIOLATION)


def own_leader_subtree(leader_id):
    if g.role == "GroupLeader" and not is_in_subtree(g.user_id, leader_id):
        raise_err(ERR_OWNERSHIP_VIOLATION)
