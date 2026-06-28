"""Derived-wallet principle (PRD §2.6 / wallet_balance_reconciliation).

A Member's wallet figures are never authoritative stored numbers; they are derived
on demand from that member's RewardClaim rows. Exact integer-cent sums, no rounding.
"""


def _member_claims(store, member_id):
    return [c for c in store.reward_claims.values() if c["member_id"] == member_id]


def compute_balances(store, member_id):
    pending = 0
    available = 0
    reserved = 0
    paid = 0
    for c in _member_claims(store, member_id):
        st = c["status"]
        amt = c["amount_cents"]
        if st == "PENDING":
            pending += amt
        elif st == "AVAILABLE":
            available += amt
        elif st == "RESERVED":
            reserved += amt
        elif st == "PAID":
            paid += amt
    # net_cashoutable == available (unreserved AVAILABLE only).
    return {
        "pending_balance_cents": pending,
        "available_balance_cents": available,
        "reserved_balance_cents": reserved,
        "net_cashoutable_cents": available,
        "lifetime_paid_cents": paid,
    }


def net_cashoutable(store, member_id):
    return compute_balances(store, member_id)["net_cashoutable_cents"]


def cumulative_qualifying_cents(store, member_id):
    """Sum of amount_cents over a member's claims in AVAILABLE or PAID
    (referral qualification basis, PRD §3.7)."""
    total = 0
    for c in _member_claims(store, member_id):
        if c["status"] in ("AVAILABLE", "PAID"):
            total += c["amount_cents"]
    return total
