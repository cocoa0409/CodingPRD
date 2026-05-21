"""Fine creation and ledger reversal."""

import state


def _record(reason, subject_type, subject_id, amount_cents, related_order_id=None):
    fid = state.gen_id()
    now = state.now()
    rec = {
        "id": fid,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "settlement_status": "PENDING",
        "related_order_id": related_order_id,
        "created_at": now,
    }
    state.STORE.fines[fid] = rec
    return rec


def issue_rider_fine(rider, reason, amount_cents, related_order_id=None):
    """Create fine + debit wallet + recompute bonus tier. Returns fine."""
    from services import riders as rsvc
    fine = _record(
        reason, "RIDER", rider["id"], amount_cents,
        related_order_id=related_order_id,
    )
    rider["wallet_balance_cents"] -= amount_cents
    rsvc.recompute_bonus_tier(rider)
    rsvc.bump(rider)
    return fine


def issue_customer_fine(customer, reason, amount_cents, related_order_id=None):
    from services import customers as csvc
    fine = _record(
        reason, "CUSTOMER", customer["id"], amount_cents,
        related_order_id=related_order_id,
    )
    # Customer balance: drawn from credit_balance (clamped to 0 minimum).
    customer["credit_balance_cents"] = max(
        0, customer["credit_balance_cents"] - amount_cents
    )
    csvc.bump(customer)
    return fine


def issue_restaurant_fine(restaurant, reason, amount_cents, related_order_id=None):
    from services import restaurants as rsvc
    fine = _record(
        reason, "RESTAURANT", restaurant["id"], amount_cents,
        related_order_id=related_order_id,
    )
    restaurant["pending_settlement_cents"] -= amount_cents
    rsvc.bump(restaurant)
    return fine


def waive(fine):
    """Reverse the ledger effect of a PENDING fine."""
    if fine["settlement_status"] != "PENDING":
        return False
    fine["settlement_status"] = "WAIVED"
    if fine["subject_type"] == "RIDER":
        from services import riders as rsvc
        r = state.STORE.riders.get(fine["subject_id"])
        if r is not None:
            r["wallet_balance_cents"] += fine["amount_cents"]
            rsvc.recompute_bonus_tier(r)
            rsvc.bump(r)
    elif fine["subject_type"] == "CUSTOMER":
        from services import customers as csvc
        c = state.STORE.customers.get(fine["subject_id"])
        if c is not None:
            c["credit_balance_cents"] += fine["amount_cents"]
            csvc.bump(c)
    elif fine["subject_type"] == "RESTAURANT":
        from services import restaurants as rsvc
        r = state.STORE.restaurants.get(fine["subject_id"])
        if r is not None:
            r["pending_settlement_cents"] += fine["amount_cents"]
            rsvc.bump(r)
    return True
