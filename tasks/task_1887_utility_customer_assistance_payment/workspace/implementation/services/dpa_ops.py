"""DPA lifecycle operations: creation/activation/cancellation, credit reversal,
derived-ledger recomputation (PRD §3.4)."""

import db
from db import CLOCK
from services.common import (round_half_up, adjust_arrearage, touch_account,
                             auto_cancel_open_order, open_order)
from services.dpa_terms import compute_terms


def recompute_dpa_derived(dpa):
    posted = sum(c["amount_cents"] for c in db.forgiveness_credits.values()
                 if c["dpa_id"] == dpa["id"] and c["status"] == "POSTED")
    dpa["forgiven_posted_cents"] = posted
    dpa["remaining_balance_cents"] = (dpa["covered_arrearage_cents"]
                                      - dpa["paid_to_arrearage_cents"] - posted)


def activate_dpa(dpa, account):
    """DRAFT -> ACTIVE: dates, protective auto-cancel, service-status flip.
    The surrounding write owns the single account version bump."""
    dpa["status"] = "ACTIVE"
    dpa["activated_on"] = CLOCK.date()
    dpa["first_installment_due_on"] = db.add_days(CLOCK.date(), 30)
    db.touch(dpa)
    # kept-current ACTIVE DPA auto-cancels any open shutoff order (PRD §3.4)
    auto_cancel_open_order(account)
    if open_order(account["id"]) is None and account["service_status"] == "DISCONNECT_PENDING":
        account["service_status"] = "CONNECTED"


def reverse_posted_credits(dpa, account):
    """Every POSTED ForgivenessCredit -> REVERSED; amounts added back onto
    account arrearage; ledger recomputed (PRD §3.4 BROKEN/CANCELLED)."""
    for c in db.forgiveness_credits.values():
        if c["dpa_id"] == dpa["id"] and c["status"] == "POSTED":
            c["status"] = "REVERSED"
            c["reversed_at"] = CLOCK.now()
            db.touch(c)
            adjust_arrearage(account, c["amount_cents"])
    recompute_dpa_derived(dpa)


def create_dpa(account, installment_count):
    """Snapshot terms, supersede a lingering DRAFT, create the row, and
    activate immediately when the down payment is zero (TIER_1 path)."""
    # supersede a DRAFT DPA on the account (quietly -> CANCELLED)
    for d in db.dpas.values():
        if d["account_id"] == account["id"] and d["status"] == "DRAFT":
            reverse_posted_credits(d, account)  # DRAFT: never any credits
            d["status"] = "CANCELLED"
            db.touch(d)
    terms = compute_terms(account, installment_count)
    dpa = {
        "id": db.new_id(),
        "account_id": account["id"],
        "status": "DRAFT",
        "covered_arrearage_cents": terms["covered_arrearage_cents"],
        "down_payment_required_cents": terms["down_payment_required_cents"],
        "down_payment_received_cents": 0,
        "installment_count": installment_count,
        "installment_amount_cents": terms["installment_amount_cents"],
        "final_installment_amount_cents": terms["final_installment_amount_cents"],
        "forgiveness_pool_cents": terms["forgiveness_pool_cents"],
        "forgiven_posted_cents": 0,
        "projected_forgiveness_cents": terms["projected_forgiveness_cents"],
        "paid_to_arrearage_cents": 0,
        "remaining_balance_cents": terms["covered_arrearage_cents"],
        "installments_settled_count": 0,
        "on_time_payment_count": 0,
        "missed_payment_count": 0,
        "activated_on": None,
        "first_installment_due_on": None,
        "defaulted_on": None,
    }
    db.stamp_common(dpa)
    db.dpas[dpa["id"]] = dpa
    if dpa["down_payment_required_cents"] == 0:
        activate_dpa(dpa, account)
    return dpa


def post_forgiveness_credit(dpa, account, installment_number):
    """Accrual rule (calc: forgiveness_accrual): installments 1..n-1 get
    round_half_up(pool/n); the final installment absorbs the remainder as
    pool minus the credits actually POSTED so far."""
    n = dpa["installment_count"]
    if installment_number < n:
        from fractions import Fraction
        amount = round_half_up(Fraction(dpa["forgiveness_pool_cents"], n))
    else:
        amount = dpa["forgiveness_pool_cents"] - dpa["forgiven_posted_cents"]
    credit = {
        "id": db.new_id(),
        "dpa_id": dpa["id"],
        "installment_number": installment_number,
        "amount_cents": amount,
        "status": "POSTED",
        "posted_at": CLOCK.now(),
        "reversed_at": None,
    }
    db.stamp_common(credit)
    db.forgiveness_credits[credit["id"]] = credit
    adjust_arrearage(account, -amount)
    recompute_dpa_derived(dpa)
    return credit
