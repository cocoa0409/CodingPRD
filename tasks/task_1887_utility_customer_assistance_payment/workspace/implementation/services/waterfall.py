"""Payment application waterfall (calc: payment_application_waterfall).

Fixed bucket order: reconnection fee -> DPA down payment -> whole installments
(oldest first, full amounts only) -> DPA extra -> arrearage -> current charges
-> overpayment credit. DPA-routed buckets set Payment.dpa_id.
"""

import db
from db import CLOCK
from services.common import (adjust_arrearage, non_terminal_dpa,
                             installment_due_date, installment_schedule_amount,
                             GRACE_DAYS, auto_cancel_open_order)
from services.dpa_ops import activate_dpa, recompute_dpa_derived, post_forgiveness_credit


def _check_completion(dpa):
    """ACTIVE -> COMPLETED when the posting leaves remaining_balance == 0."""
    if dpa["status"] == "ACTIVE" and dpa["remaining_balance_cents"] == 0:
        dpa["status"] = "COMPLETED"
        db.touch(dpa)


def post_payment(account, amount_cents, tender_type):
    remaining = amount_cents
    breakdown = {
        "reconnection_fee_cents": 0,
        "down_payment_cents": 0,
        "installment_cents": 0,
        "dpa_extra_cents": 0,
        "arrearage_cents": 0,
        "current_charges_cents": 0,
        "overpayment_cents": 0,
    }
    settled_count = 0
    settled_all_on_time = True
    credit_accrued = 0
    dpa_touched = None

    dpa = non_terminal_dpa(account["id"])

    # 1. reconnection fee
    if remaining > 0 and account["reconnection_fee_due_cents"] > 0:
        pay = min(remaining, account["reconnection_fee_due_cents"])
        account["reconnection_fee_due_cents"] -= pay
        breakdown["reconnection_fee_cents"] = pay
        remaining -= pay

    # 2. DPA down payment (DRAFT)
    if remaining > 0 and dpa is not None and dpa["status"] == "DRAFT":
        shortfall = dpa["down_payment_required_cents"] - dpa["down_payment_received_cents"]
        if shortfall > 0:
            pay = min(remaining, shortfall)
            dpa["down_payment_received_cents"] += pay
            dpa["paid_to_arrearage_cents"] += pay
            adjust_arrearage(account, -pay)
            breakdown["down_payment_cents"] = pay
            remaining -= pay
            dpa_touched = dpa
            recompute_dpa_derived(dpa)
            db.touch(dpa)
            if dpa["down_payment_received_cents"] >= dpa["down_payment_required_cents"]:
                activate_dpa(dpa, account)

    # 3. whole scheduled installments, oldest first. ACTIVE per the waterfall
    # formula; DEFAULTED is also served so the reinstate cure path (which
    # requires all due installments settled) is reachable at all (PRD §3.4).
    if remaining > 0 and dpa is not None and dpa["status"] in ("ACTIVE", "DEFAULTED"):
        n = dpa["installment_count"]
        today = CLOCK.date()
        while dpa["installments_settled_count"] < n:
            k = dpa["installments_settled_count"] + 1
            amt = installment_schedule_amount(dpa, k)
            if remaining < amt:
                break
            remaining -= amt
            dpa["paid_to_arrearage_cents"] += amt
            dpa["installments_settled_count"] += 1
            adjust_arrearage(account, -amt)
            breakdown["installment_cents"] += amt
            dpa_touched = dpa
            on_time = today <= db.add_days(installment_due_date(dpa, k), GRACE_DAYS)
            settled_count += 1
            if on_time:
                dpa["on_time_payment_count"] += 1
                credit = post_forgiveness_credit(dpa, account, k)
                credit_accrued += credit["amount_cents"]
            else:
                settled_all_on_time = False
            recompute_dpa_derived(dpa)
            db.touch(dpa)

    # 4. DPA extra arrearage (ACTIVE|DRAFT), capped at the agreement remainder
    if remaining > 0 and dpa is not None and dpa["status"] in ("ACTIVE", "DRAFT"):
        pay = min(remaining, dpa["remaining_balance_cents"])
        if pay > 0:
            dpa["paid_to_arrearage_cents"] += pay
            adjust_arrearage(account, -pay)
            breakdown["dpa_extra_cents"] = pay
            remaining -= pay
            dpa_touched = dpa
            recompute_dpa_derived(dpa)
            db.touch(dpa)

    if dpa is not None:
        _check_completion(dpa)

    # 5. account arrearage
    if remaining > 0 and account["arrearage_balance_cents"] > 0:
        pay = min(remaining, account["arrearage_balance_cents"])
        adjust_arrearage(account, -pay)
        breakdown["arrearage_cents"] = pay
        remaining -= pay

    # 6. current charges
    if remaining > 0 and account["current_charges_balance_cents"] > 0:
        pay = min(remaining, account["current_charges_balance_cents"])
        account["current_charges_balance_cents"] -= pay
        breakdown["current_charges_cents"] = pay
        remaining -= pay

    # 7. overpayment credit
    if remaining > 0:
        account["credit_balance_cents"] += remaining
        breakdown["overpayment_cents"] = remaining
        remaining = 0

    payment = {
        "id": db.new_id(),
        "account_id": account["id"],
        "dpa_id": dpa_touched["id"] if dpa_touched is not None else None,
        "amount_cents": amount_cents,
        "tender_type": tender_type,
        "paid_at": CLOCK.now(),
        "applied_breakdown": breakdown,
        "installments_settled_count": settled_count,
        "on_time": (settled_all_on_time if settled_count > 0 else None),
        "credit_accrued_cents": credit_accrued,
        "created_at": CLOCK.now(),
        "_seq": db.next_seq(),
    }
    db.payments[payment["id"]] = payment

    # post-payment reconciliation: delinquency derives at read; auto-cancel check
    auto_cancel_open_order(account)
    return payment
