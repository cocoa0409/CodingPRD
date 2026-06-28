"""Session-level derived ledger helpers: retouch credit reservation and
commission accrual/reconciliation (SCAFFOLD §1.3, PRD §3.5 / §3.7).

The retouch credit balance is, equivalently, budget minus the sum of
net_cost_cents over every retouch order in APPROVED|DONE (PRD §3.5). It is
maintained incrementally: reserve on approve, release on cancel-of-approved.
Each balance change is a session mutation (version +1, updated_at refresh).
"""
import store
from common import commission_rate, round_half_up


def reserve_retouch_credit(session, amount):
    """Reserve credit on retouch approval: balance -= amount; bump session."""
    session["retouch_credit_balance_cents"] -= amount
    store.touch(session)


def release_retouch_credit(session, amount):
    """Release a previously reserved amount back to the balance; bump session."""
    session["retouch_credit_balance_cents"] += amount
    store.touch(session)


def accrue_provisional_commission(session, order):
    """On pay(): rate keyed to running cumulative gross AFTER this order;
    round per order then add. Also increases total_merchandise_cents.
    Both updates are one session mutation (single version bump)."""
    running_gross = session["total_merchandise_cents"]
    merch = order["merchandise_cents"]
    new_gross = running_gross + merch
    rate = commission_rate(new_gross)
    line_commission = round_half_up(merch * rate)

    session["school_commission_balance_cents"] += line_commission
    session["total_merchandise_cents"] = new_gross
    store.touch(session)


def reconcile_final_commission(session, orders_for_session):
    """On settle(): single rate keyed to total gross over PAID|FULFILLED orders;
    one round over the total (sum-then-round). Sets school_commission_balance.
    The caller bumps the session version as part of the settle transition."""
    total_gross = sum(
        o["merchandise_cents"]
        for o in orders_for_session
        if o["status"] in ("PAID", "FULFILLED")
    )
    final_rate = commission_rate(total_gross)
    final_commission = round_half_up(total_gross * final_rate)
    session["school_commission_balance_cents"] = final_commission
