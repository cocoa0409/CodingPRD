"""Shared cascade / ledger helpers. Conserved quantities never drift (PRD 2.8)."""
import store


def policy_move(policy, delta):
    """Move a policy's remaining frame allowance. A zero move is not a mutation."""
    if policy is None or delta == 0:
        return
    policy["frame_allowance_remaining_cents"] += delta
    store.touch(policy)


def customer_fsa_move(customer, delta):
    if delta == 0:
        return
    customer["fsa_balance_cents"] += delta
    store.touch(customer)


def void_claim(claim):
    """Compensating edge: restores the exact benefit dollars the claim reserved."""
    claim["status"] = "VOID"
    store.touch(claim)
    policy_move(store.policies.get(claim["policy_id"]), claim["reserved_frame_benefit_cents"])


def order_policy(order):
    customer = store.customers.get(order["customer_id"])
    if customer is None or not customer.get("insurance_policy_id"):
        return None
    return store.policies.get(customer["insurance_policy_id"])


def lab_orders_for(order_id):
    return [lo for lo in store.ordered(store.lab_orders) if lo["order_id"] == order_id]
