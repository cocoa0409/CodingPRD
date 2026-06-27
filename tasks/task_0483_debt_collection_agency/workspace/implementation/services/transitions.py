"""Shared cross-entity transition helpers: ledger recompute bundles, auto-close,
recall cascade, dispute-DELETED account closure. Kept separate to avoid import
cycles between route modules."""
from db import db, touch
from services.accounts import (
    recompute_ledger,
    recompute_commission,
    recompute_last_payment_date,
)

TERMINAL_WORK = {"CLOSED_PAID", "CLOSED_UNCOLLECTIBLE"}


def recompute_account_financials(account):
    """Recompute the full derived financial picture and persist on the account."""
    recompute_ledger(account)
    recompute_last_payment_date(account)
    recompute_commission(account)


def maybe_auto_close_paid(account):
    """Auto-close to CLOSED_PAID when balance reaches 0 while WORKING."""
    if account["work_status"] == "WORKING" and account["balance_cents"] == 0:
        account["work_status"] = "CLOSED_PAID"
        recompute_commission(account)
        touch(account)
        return True
    return False


def try_fulfill_arrangements(account):
    """After a payment posts, check ACCEPTED arrangements tied to this account
    and auto-fulfill any whose posted payments now satisfy it. Settlement
    fulfillment forgives the difference and drives balance to zero."""
    for arr in db.arrangements.values():
        if arr["account_id"] != account["id"]:
            continue
        if arr["status"] != "ACCEPTED":
            continue
        paid = sum(
            p["amount_cents"] for p in db.payments.values()
            if p.get("arrangement_id") == arr["id"] and p["status"] == "POSTED"
        )
        if arr["arrangement_type"] == "SETTLEMENT":
            target = arr.get("settlement_amount_cents")
            if target is not None and paid >= target:
                bal_at_accept = arr.get("balance_at_acceptance", account["balance_cents"])
                forgiven = bal_at_accept - target
                if forgiven > 0:
                    account["amount_settled_forgiven_cents"] = (
                        account.get("amount_settled_forgiven_cents", 0) + forgiven
                    )
                arr["status"] = "FULFILLED"
                touch(arr)
                recompute_ledger(account)
                recompute_commission(account)
        else:  # PLAN
            target = arr.get("balance_at_acceptance", account["balance_cents"])
            if paid >= target:
                arr["status"] = "FULFILLED"
                touch(arr)


def recall_cascade(account):
    """Three-level recall cascade (PRD 3.8).

    L1: PROPOSED/ACCEPTED/COUNTERED arrangements on the account -> CANCELLED.
    L2: each just-cancelled arrangement voids its POSTED payments -> VOIDED.
    L3: each voided payment restores the ledger (handled by ledger recompute,
        since VOIDED payments drop out of the POSTED sum).
    """
    cancellable = {"PROPOSED", "ACCEPTED", "COUNTERED"}
    cancelled_ids = []
    for arr in db.arrangements.values():
        if arr["account_id"] != account["id"]:
            continue
        if arr["status"] in cancellable:
            arr["status"] = "CANCELLED"
            touch(arr)
            cancelled_ids.append(arr["id"])
    # L2: void POSTED payments tied to a just-cancelled arrangement.
    for pay in db.payments.values():
        if pay["account_id"] != account["id"]:
            continue
        if pay["status"] != "POSTED":
            continue
        if pay.get("arrangement_id") in cancelled_ids:
            pay["status"] = "VOIDED"
            touch(pay)
    # L3: ledger restoration is implicit — recompute from remaining POSTED payments.
    recompute_account_financials(account)


def close_account_uncollectible_via_dispute(account):
    """Auto-close path when an open dispute resolves DELETED (PRD 3.4)."""
    account["work_status"] = "CLOSED_UNCOLLECTIBLE"
    recompute_commission(account)
    touch(account)
    # Cascade: open BureauFurnishing rows for this account -> DELETED.
    for f in db.bureau_furnishings.values():
        if f["account_id"] != account["id"]:
            continue
        if f["status"] != "DELETED":
            f["status"] = "DELETED"
            touch(f)
