"""Test-driving billing ticks: run-renewals and run-dunning (PRD §3.3, §3.7)."""
from db import db, touch
from util import (
    add_days, CYCLE_DAYS, DUNNING_MAX_ATTEMPTS, DUNNING_RETRY_OFFSETS_DAYS,
)
from services import billing


# =============================================================================
# run-renewals (PRD §3.3): convert TRIALING (trial_end <= now), renew ACTIVE
# (period_end <= now).
# =============================================================================
def run_renewals():
    now = db.now()
    converted = 0
    renewed = 0
    invoice_ids = []

    # Deterministic order by created_at.
    subs = sorted(db.subscriptions.values(), key=lambda s: (s["created_at"], s["id"]))

    # Pass 1: convert trials whose trial_end is at/before the clock.
    for sub in subs:
        if sub["lifecycle_status"] != "TRIALING":
            continue
        if sub.get("trial_end") is None:
            continue
        if sub["trial_end"] <= now:
            inv = _convert_trial_auto(sub)
            converted += 1
            if inv:
                invoice_ids.append(inv["id"])

    # Pass 2: renew ACTIVE subscriptions whose period_end is at/before the clock.
    for sub in subs:
        if sub["lifecycle_status"] != "ACTIVE":
            continue
        if sub["period_end"] <= now:
            inv = _renew_active(sub)
            renewed += 1
            if inv:
                invoice_ids.append(inv["id"])

    return {
        "converted_count": converted,
        "renewed_count": renewed,
        "invoice_ids": invoice_ids,
    }


def _convert_trial_auto(sub):
    """Auto-convert at renewal tick (PRD §3.3): period_start = trial_end,
    period_end = trial_end + 30 days. Requires plan still ACTIVE."""
    from errors import ApiError, ERR_PLAN_ARCHIVED
    plan = db.plans.get(sub["plan_id"])
    if plan is None or plan["status"] == "ARCHIVED":
        raise ApiError(ERR_PLAN_ARCHIVED, 409,
                       "Plan referenced by subscription is archived")
    account = db.accounts.get(sub["account_id"])

    sub["lifecycle_status"] = "ACTIVE"
    sub["period_start"] = sub["trial_end"]
    sub["period_end"] = add_days(sub["trial_end"], CYCLE_DAYS)
    touch(sub)

    invoice = billing.build_cycle_invoice(
        sub, account, plan, sub["period_start"], sub["period_end"],
        include_overage=True)
    billing.reconcile_subscription_and_account(sub)
    return invoice


def _renew_active(sub):
    """Renew an ACTIVE subscription (PRD §3.3): finalize next cycle invoice incl.
    the closing cycle's overage sweep, advance billing period by 30 days.

    The invoice's service period is the *next* cycle (subscription fee charged
    in advance), while overage is swept from the *closing* cycle that is ending.
    """
    plan = db.plans.get(sub["plan_id"])
    account = db.accounts.get(sub["account_id"])
    closing_start = sub["period_start"]
    closing_end = sub["period_end"]
    new_period_start = sub["period_end"]
    new_period_end = add_days(new_period_start, CYCLE_DAYS)

    invoice = billing.build_cycle_invoice(
        sub, account, plan, new_period_start, new_period_end,
        include_overage=True, overage_window=(closing_start, closing_end))

    sub["period_start"] = new_period_start
    sub["period_end"] = new_period_end
    touch(sub)
    billing.reconcile_subscription_and_account(sub)
    return invoice


# =============================================================================
# run-dunning (PRD §3.7): for each OPEN/PAST_DUE invoice whose retry is due,
# attempt payment and advance the dunning state machine.
# =============================================================================
def run_dunning():
    now = db.now()
    retried = 0
    cleared = 0
    canceled_subscription_ids = []

    invoices = sorted(db.invoices.values(), key=lambda i: (i["created_at"], i["id"]))
    for invoice in invoices:
        if invoice["status"] not in ("OPEN", "PAST_DUE"):
            continue
        sub = db.subscriptions.get(invoice["subscription_id"])
        if sub is None:
            continue

        due = _retry_due(invoice, sub, now)
        if not due:
            continue

        retried += 1
        result = _attempt_dunning(invoice, sub)
        if result == "cleared":
            cleared += 1
        elif result == "canceled":
            canceled_subscription_ids.append(sub["id"])

    return {
        "retried_count": retried,
        "cleared_count": cleared,
        "canceled_subscription_ids": canceled_subscription_ids,
    }


def _retry_due(invoice, sub, now):
    """A retry is due when now >= next_retry_at, or it is the first attempt
    (PRD §3.7). An OPEN invoice with no recorded payment yet is a first attempt;
    a PAST_DUE invoice is due once now >= next_retry_at."""
    if sub["billing_status"] == "PAST_DUE":
        nra = sub.get("next_retry_at")
        return nra is not None and now >= nra
    # OPEN invoice that has never been attempted (no payment): first attempt.
    if invoice["status"] == "OPEN":
        has_payment = any(p["invoice_id"] == invoice["id"] for p in db.payments.values())
        return not has_payment
    return False


def _next_attempt_number(invoice):
    n = 0
    for p in db.payments.values():
        if p["invoice_id"] == invoice["id"]:
            n = max(n, p["attempt_number"])
    return n + 1


def _attempt_dunning(invoice, sub):
    """Run one due retry. Returns 'cleared' | 'past_due' | 'canceled'."""
    account = db.accounts.get(invoice["account_id"])
    ok = bool(account.get("payment_method_ok", True))
    attempt_number = _next_attempt_number(invoice)

    if sub["billing_status"] == "PAST_DUE":
        # Queued retry: invoice reverts PAST_DUE -> OPEN so the attempt can run.
        invoice["status"] = "OPEN"
        touch(invoice)

    if ok:
        billing._create_payment(invoice, attempt_number, "CLEARED")
        billing._mark_invoice_paid(invoice, sub)
        return "cleared"

    # Payment failed.
    billing._create_payment(invoice, attempt_number, "FAILED")

    if sub["billing_status"] != "PAST_DUE":
        # First failure path (rare via dunning; usually happens at finalize).
        billing._begin_dunning_on_first_failure(invoice, sub)
        return "past_due"

    # Already PAST_DUE: increment attempt, decide self-loop vs involuntary churn.
    sub["dunning_attempt"] = sub["dunning_attempt"] + 1

    if sub["dunning_attempt"] >= DUNNING_MAX_ATTEMPTS:
        # Final retry failed -> involuntary churn (PRD §3.7).
        lost_mrr = sub["mrr_contribution_cents"]
        billing.record_churn(sub, lost_mrr)
        sub["billing_status"] = "UNPAID"
        sub["lifecycle_status"] = "CANCELED"
        sub["mrr_contribution_cents"] = 0
        sub["next_retry_at"] = None
        touch(sub)
        invoice["status"] = "VOID"
        touch(invoice)
        billing.reconcile_subscription_and_account(sub)
        return "canceled"

    # Self-loop: stay PAST_DUE, advance next_retry_at.
    first_failure = sub.get("_first_failure_at", db.now())
    sub["next_retry_at"] = add_days(first_failure,
                                    DUNNING_RETRY_OFFSETS_DAYS[sub["dunning_attempt"]])
    sub["billing_status"] = "PAST_DUE"
    touch(sub)
    invoice["status"] = "PAST_DUE"
    touch(invoice)
    return "past_due"
