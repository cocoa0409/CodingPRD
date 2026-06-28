"""Recurring-billing driver (PRD §3.4, §3.6; scaffold §1.5 POST /_billing/run).

Idempotent for a fixed clock: it walks every subscription whose clock has
reached or passed current_cycle_end_at and acts by status, and expires credit
packs past expires_at. Returns counts of subscriptions renewed, subscriptions
unfrozen, and packs expired.
"""

from clock import clock, parse_iso8601, format_iso8601_ms
from db import db, new_id, now_ts
from helpers import touch
from services.calculations import FREEZE_FEE_CENTS
from services.compute import (
    subscription_current_cycle_end_at_dt,
    recompute_lifetime_paid,
    recompute_credit_balance_by_member_id,
)


def _append_invoice(subscription_id, kind, amount_cents):
    inv = {
        "id": new_id(),
        "created_at": now_ts(),
        "_seq": db.next_seq(),
        "subscription_id": subscription_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "PAID",
    }
    db.invoices[inv["id"]] = inv
    return inv


def _plan_for(sub):
    return db.membership_plans.get(sub["plan_id"])


def _renew_active(sub):
    """ACTIVE->ACTIVE cyclic renewal (PRD §3.4)."""
    plan = _plan_for(sub)
    _append_invoice(sub["id"], "RENEWAL", plan["monthly_fee_cents"])
    # Advance anchor to the previous current_cycle_end_at; recompute end.
    prior_end = subscription_current_cycle_end_at_dt(sub)
    sub["cycle_anchor_at"] = format_iso8601_ms(prior_end)
    # Replenish: grant + min(rollover_cap, prior granted_credits_remaining).
    prior_granted = sub["granted_credits_remaining"]
    carried = min(plan["rollover_cap"], prior_granted)
    sub["granted_credits_remaining"] = plan["monthly_credit_grant"] + carried
    touch(sub)
    recompute_lifetime_paid(sub)
    recompute_credit_balance_by_member_id(sub["member_id"])


def _freeze_fee_cycle(sub):
    """FROZEN->FROZEN self-transition when more than one frozen cycle remains."""
    _append_invoice(sub["id"], "FREEZE_FEE", FREEZE_FEE_CENTS)
    prior_end = subscription_current_cycle_end_at_dt(sub)
    sub["cycle_anchor_at"] = format_iso8601_ms(prior_end)
    sub["freeze_cycles_remaining"] -= 1
    touch(sub)
    recompute_lifetime_paid(sub)


def _auto_unfreeze(sub):
    """FROZEN->ACTIVE auto-unfreeze when freeze_cycles_remaining reaches 0."""
    plan = _plan_for(sub)
    sub["status"] = "ACTIVE"
    sub["freeze_cycles_remaining"] = 0
    sub["cycle_anchor_at"] = now_ts()
    sub["granted_credits_remaining"] = plan["monthly_credit_grant"]
    touch(sub)
    recompute_credit_balance_by_member_id(sub["member_id"])


def run_billing():
    subscriptions_renewed = 0
    subscriptions_unfrozen = 0
    packs_expired = 0

    now = clock.now()

    # --- Subscriptions: walk each, advancing cycles while the clock has passed
    #     current_cycle_end_at. A frozen subscription may consume several frozen
    #     cycles (freeze fee each) until freeze_cycles_remaining hits 1, then the
    #     final frozen cycle auto-unfreezes back to ACTIVE; an ACTIVE subscription
    #     renews each elapsed cycle.
    for sub in list(db.subscriptions.values()):
        if sub["status"] == "CANCELLED":
            continue
        # Loop while a full cycle has elapsed (idempotent for a fixed clock).
        guard = 0
        while now >= subscription_current_cycle_end_at_dt(sub) and guard < 100000:
            guard += 1
            if sub["status"] == "ACTIVE":
                _renew_active(sub)
                subscriptions_renewed += 1
            elif sub["status"] == "FROZEN":
                if sub["freeze_cycles_remaining"] > 1:
                    _freeze_fee_cycle(sub)
                else:
                    # Last frozen cycle elapsed -> auto-unfreeze to ACTIVE,
                    # re-anchoring to the current clock (no further renewal this run
                    # unless the new anchor is itself already a full cycle behind).
                    _auto_unfreeze(sub)
                    subscriptions_unfrozen += 1
            else:
                break

    # --- Credit packs: expire ACTIVE packs whose clock has reached expires_at.
    for pack in list(db.credit_packs.values()):
        if pack["status"] != "ACTIVE":
            continue
        if now >= parse_iso8601(pack["expires_at"]):
            pack["remaining_credits"] = 0
            pack["status"] = "EXPIRED"
            touch(pack)
            recompute_credit_balance_by_member_id(pack["member_id"])
            packs_expired += 1

    return {
        "subscriptions_renewed": subscriptions_renewed,
        "subscriptions_unfrozen": subscriptions_unfrozen,
        "packs_expired": packs_expired,
    }
