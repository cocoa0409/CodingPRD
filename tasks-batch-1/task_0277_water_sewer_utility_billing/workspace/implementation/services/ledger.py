"""Derived ledger reconciliation and the payment waterfall (PRD §2.5, §3.6).

The account's money fields are never set directly: they are recomputed from the
underlying facts (POSTED/PAID bills, RECONNECTED shutoff orders, payments) plus a
persistent true-up adjustment that the true-up workflow posts to the ledger.
"""
import db


def account_bills(account_id):
    return [b for b in db.bills.values() if b["account_id"] == account_id]


def account_payments(account_id):
    return [p for p in db.payments.values() if p["account_id"] == account_id]


def account_shutoffs(account_id):
    return [s for s in db.shutoff_orders.values() if s["account_id"] == account_id]


def _payments_applied_to_bill(account_id, bill_id):
    """Cents of payment that landed on a specific bill via the waterfall."""
    total = 0
    for p in account_payments(account_id):
        total += p.get("_allocations", {}).get(bill_id, 0)
    return total


def recompute_balances(account):
    """Recompute balance_due_cents and past_due_cents (PRD §2.5).

    balance_due = sum(total_cents of POSTED|PAID bills)
                + sum(late_fee_cents of those bills)
                + sum(reconnect_fee_charged_cents of RECONNECTED orders)
                - sum(amount_cents of all payments)
                + persistent true-up adjustment
                floored at 0.

    past_due = sum(total_cents + late_fee_cents for bills POSTED with CLOSED
               cycle) - payments absorbed by those bills, floored at 0.
    """
    aid = account["id"]
    bills = account_bills(aid)

    posted_charges = 0
    late_fees = 0
    for b in bills:
        if b["status"] in ("POSTED", "PAID"):
            posted_charges += b["total_cents"]
            late_fees += b["late_fee_cents"]

    reconnect_fees = 0
    for s in account_shutoffs(aid):
        if s["status"] == "RECONNECTED":
            reconnect_fees += s["reconnect_fee_charged_cents"]

    payments_total = sum(p["amount_cents"] for p in account_payments(aid))
    trueup_adj = account.get("_trueup_adjustment_cents", 0)

    balance = posted_charges + late_fees + reconnect_fees - payments_total + trueup_adj
    account["balance_due_cents"] = max(0, balance)

    past_due = 0
    for b in bills:
        if b["status"] != "POSTED":
            continue
        cycle = db.billing_cycles.get(b["billing_cycle_id"])
        if cycle is None or cycle["status"] != "CLOSED":
            continue
        absorbed = _payments_applied_to_bill(aid, b["id"])
        past_due += (b["total_cents"] + b["late_fee_cents"]) - absorbed
    account["past_due_cents"] = max(0, past_due)


def recompute_derived_flags(account):
    """budget_billing_enrolled / assistance_enrolled (PRD §2.5)."""
    aid = account["id"]
    account["budget_billing_enrolled"] = any(
        pl["account_id"] == aid and pl["status"] == "ACTIVE"
        for pl in db.budget_plans.values()
    )
    account["assistance_enrolled"] = any(
        en["account_id"] == aid and en["status"] == "ACTIVE"
        for en in db.assistance_enrollments.values()
    )


def reconcile(account):
    """Full account recompute + bump updated_at/version (a mutation, PRD §2.5)."""
    recompute_derived_flags(account)
    recompute_balances(account)
    db.touch(account)


def active_budget_plan(account_id):
    for pl in db.budget_plans.values():
        if pl["account_id"] == account_id and pl["status"] == "ACTIVE":
            return pl
    return None


def apply_payment_waterfall(account, payment):
    """Apply a payment oldest-first across POSTED unpaid bills (PRD §3.6).

    Records per-bill allocations on the payment (_allocations), sets the
    public applied_to_bill_id pointer (oldest bill it landed on, or null), and
    flips bills POSTED -> PAID once cumulative applied >= total_cents.
    Returns the list of bills that newly transitioned to PAID.
    """
    aid = account["id"]
    amount = payment["amount_cents"]

    # Oldest POSTED unpaid bills first (created_at ASC, tie-break internal seq).
    posted = [b for b in account_bills(aid) if b["status"] == "POSTED"]
    posted.sort(key=lambda b: (b["created_at"], b["_seq"]))

    allocations = {}
    applied_to = None
    newly_paid = []
    remaining = amount

    for b in posted:
        if remaining <= 0:
            break
        already = _payments_applied_to_bill(aid, b["id"])
        owed = b["total_cents"] - already
        if owed <= 0:
            continue
        give = min(remaining, owed)
        allocations[b["id"]] = give
        remaining -= give
        if applied_to is None:
            applied_to = b["id"]
        # Did this payment bring the bill to fully covered?
        if already + give >= b["total_cents"]:
            b["status"] = "PAID"
            db.touch(b)
            newly_paid.append(b)

    payment["_allocations"] = allocations
    # applied_to_bill_id: oldest POSTED unpaid bill the payment landed on, else null.
    payment["applied_to_bill_id"] = applied_to
    return newly_paid
