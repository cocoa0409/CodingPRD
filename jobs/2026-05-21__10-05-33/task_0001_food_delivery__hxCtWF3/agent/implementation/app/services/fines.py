"""Fine creation + waive."""
from flask import g

from ..auth import parse_headers, require_role
from ..clock import format_iso
from ..envelope import success
from ..errors import fail
from ..ids import new_uuid
from ..resource import bump
from ..server import store, clock


def create_fine(subject_type: str, subject_id: str, reason: str, amount_cents: int) -> dict:
    """Create a fine and debit the appropriate ledger. Also re-evaluates rider bonus tier."""
    f = {
        "id": new_uuid(),
        "created_at": format_iso(clock.now()),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "settlement_status": "PENDING",
    }
    store.fines[f["id"]] = f
    # Ledger side-effects per subject
    if subject_type == "RIDER":
        rider = store.riders.get(subject_id)
        if rider:
            rider["wallet_balance_cents"] -= amount_cents
            from ..formulas import bonus_tier
            rider["bonus_tier"] = bonus_tier(rider["on_time_rate"], rider["acceptance_rate"], rider["rating"])
            bump(rider)
    elif subject_type == "CUSTOMER":
        customer = store.customers.get(subject_id)
        if customer:
            # Debit the customer's credit balance by the fine amount, but not below zero.
            customer["credit_balance_cents"] = max(0, customer["credit_balance_cents"] - amount_cents)
            bump(customer)
    elif subject_type == "RESTAURANT":
        restaurant = store.restaurants.get(subject_id)
        if restaurant:
            restaurant["pending_settlement_cents"] -= amount_cents
            bump(restaurant)
    return f


def waive_fine(fid):
    parse_headers()
    require_role("CustomerService", "PlatformAdmin")
    f = store.fines.get(fid)
    if not f:
        raise fail("ERR_NOT_FOUND")
    if f["settlement_status"] != "PENDING":
        raise fail("ERR_INVALID_STATE")
    # Reverse ledger
    amount = f["amount_cents"]
    if f["subject_type"] == "RIDER":
        rider = store.riders.get(f["subject_id"])
        if rider:
            rider["wallet_balance_cents"] += amount
            from ..formulas import bonus_tier
            rider["bonus_tier"] = bonus_tier(rider["on_time_rate"], rider["acceptance_rate"], rider["rating"])
            bump(rider)
    elif f["subject_type"] == "CUSTOMER":
        customer = store.customers.get(f["subject_id"])
        if customer:
            customer["credit_balance_cents"] += amount
            bump(customer)
    elif f["subject_type"] == "RESTAURANT":
        restaurant = store.restaurants.get(f["subject_id"])
        if restaurant:
            restaurant["pending_settlement_cents"] += amount
            bump(restaurant)
    f["settlement_status"] = "WAIVED"
    return success(f)
