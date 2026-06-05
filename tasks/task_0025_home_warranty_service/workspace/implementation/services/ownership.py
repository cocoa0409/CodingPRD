"""Customer ownership enforcement (PRD §2.1, §1.7 RBAC matrix).

For Customer role:
  - X-User-ID equals the acting Customer.id
  - Ownership is enforced server-side: the Customer must equal
    Contract.customer_id (directly on Contract, or transitively through
    contract_id for covered items, claims, renewal reminders).

The scaffold validations table places ownership/RBAC under priority 2
(ERR_FORBIDDEN). Path/FK-id existence (priority 3-4, ERR_NOT_FOUND) is
checked first.
"""
from __future__ import annotations

from typing import Dict, Any

from errors import APIError, ERR_FORBIDDEN


def assert_customer_owns_contract(contract: Dict[str, Any], role: str, user_id: str) -> None:
    """If role is Customer, enforce contract.customer_id == user_id."""
    if role == "Customer":
        if contract.get("customer_id") != user_id:
            raise APIError(ERR_FORBIDDEN, 403, "Customer does not own this contract")


def assert_customer_owns_customer(customer_row: Dict[str, Any], role: str, user_id: str) -> None:
    """If role is Customer, enforce customer.id == user_id."""
    if role == "Customer":
        if customer_row.get("id") != user_id:
            raise APIError(ERR_FORBIDDEN, 403, "Customer can only access own record")
