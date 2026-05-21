"""Fine creation + waive logic with ledger cascades."""

from __future__ import annotations

from clock import CLOCK
from ids import new_id
from resources import touch
from store import STORE


def _make_fine(subject_type: str, subject_id: str, reason: str, amount_cents: int) -> dict:
    fine = {
        "id": new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": reason,
        "amount_cents": int(amount_cents),
        "settlement_status": "PENDING",
        "created_at": CLOCK.now_iso(),
    }
    STORE.fines[fine["id"]] = fine
    return fine


def create_rider_fine(rider_id: str, reason: str, amount_cents: int) -> dict:
    """Create a fine on a RIDER, debit wallet, recompute bonus tier."""
    rider = STORE.riders[rider_id]
    fine = _make_fine("RIDER", rider_id, reason, amount_cents)
    rider["wallet_balance_cents"] = int(rider["wallet_balance_cents"]) - int(amount_cents)
    from rider_metrics import recompute_bonus_tier
    recompute_bonus_tier(rider)
    touch(rider)
    return fine


def create_customer_fine(customer_id: str, reason: str, amount_cents: int) -> dict:
    """Customer fine. PRD describes ABUSIVE_RETURN with amount_cents = approved_refund_cents
    on top of the existing refund credit. The fine's debit reverses customer credit when waived."""
    customer = STORE.customers[customer_id]
    fine = _make_fine("CUSTOMER", customer_id, reason, amount_cents)
    # The fine itself is owed by the customer — at fine creation time we deduct from credit_balance.
    customer["credit_balance_cents"] = max(0, int(customer["credit_balance_cents"]) - int(amount_cents))
    touch(customer)
    return fine


def create_restaurant_fine(restaurant_id: str, reason: str, amount_cents: int) -> dict:
    restaurant = STORE.restaurants[restaurant_id]
    fine = _make_fine("RESTAURANT", restaurant_id, reason, amount_cents)
    restaurant["pending_settlement_cents"] = int(restaurant["pending_settlement_cents"]) - int(amount_cents)
    touch(restaurant)
    return fine


def waive_fine(fine: dict) -> None:
    """Move PENDING -> WAIVED and reverse the prior ledger effect."""
    if fine["settlement_status"] != "PENDING":
        from errors import APIError
        raise APIError("ERR_INVALID_STATE", "Only PENDING fines can be waived.")
    fine["settlement_status"] = "WAIVED"
    subject = fine["subject_type"]
    amount = int(fine["amount_cents"])
    if subject == "RIDER":
        rider = STORE.riders.get(fine["subject_id"])
        if rider is not None:
            rider["wallet_balance_cents"] = int(rider["wallet_balance_cents"]) + amount
            from rider_metrics import recompute_bonus_tier
            recompute_bonus_tier(rider)
            touch(rider)
    elif subject == "CUSTOMER":
        customer = STORE.customers.get(fine["subject_id"])
        if customer is not None:
            customer["credit_balance_cents"] = int(customer["credit_balance_cents"]) + amount
            touch(customer)
    elif subject == "RESTAURANT":
        restaurant = STORE.restaurants.get(fine["subject_id"])
        if restaurant is not None:
            restaurant["pending_settlement_cents"] = int(restaurant["pending_settlement_cents"]) + amount
            touch(restaurant)
