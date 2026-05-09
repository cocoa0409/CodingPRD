"""Payment reconciliation against fee bills.

PRD §3.6:
  - (channel, external_txn_id) is the idempotency key -> ERR_DUPLICATE_PAYMENT
  - amount > 0 and amount <= 10 * total_due
  - reconcile immediately on create:
      OPEN  + 0 < paid < total + now <= due  -> PARTIALLY_PAID
      OVERDUE + 0 < paid < total             -> PARTIALLY_PAID
      paid >= total                          -> PAID
  - on PAID: freeze late_fee, dunning_stage = NONE, recompute owner voting_status.
"""
from __future__ import annotations

import db
from errors import (
    APIError,
    ERR_DUPLICATE_PAYMENT,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_REFERENCE_NOT_FOUND,
)
from services.common import bump, stamp_create
from services.fees import refresh_late_fee
from services.voting_status import recompute_for_owner
from utils import iso_format, parse_iso, round2_dec, to_decimal


def _is_duplicate(channel: str, external_txn_id: str) -> bool:
    return any(
        p.get("channel") == channel and p.get("external_txn_id") == external_txn_id
        for p in db.payment_records.values()
    )


def record_payment(*, bill_id: str, channel: str, external_txn_id: str,
                   amount, paid_at_str: str) -> dict:
    bill = db.fee_bills.get(bill_id)
    if bill is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"FeeBill {bill_id} not found.", 404)

    with db.mutation_lock:
        # 1. Idempotency check
        if _is_duplicate(channel, external_txn_id):
            raise APIError(
                ERR_DUPLICATE_PAYMENT,
                f"Payment with external_txn_id={external_txn_id} on {channel} already recorded.",
                409,
            )

        # 2. Refresh late fee so total_due is current for the sanity check.
        if bill.get("status") in ("OPEN", "OVERDUE", "PARTIALLY_PAID"):
            refresh_late_fee(bill)
        total_due = to_decimal(bill.get("total_due", 0))
        amt = to_decimal(amount)
        if amt <= 0 or amt > to_decimal(10) * total_due:
            raise APIError(
                ERR_PAYMENT_AMOUNT_INVALID,
                "Payment amount must be > 0 and <= 10 * total_due.",
                422,
            )

        paid_at = parse_iso(paid_at_str, field="paid_at")

        record = {
            "bill_id": bill_id,
            "channel": channel,
            "external_txn_id": external_txn_id,
            "amount": float(round2_dec(amt)),
            "paid_at": iso_format(paid_at),
            "reconciliation_status": "RECONCILED",
        }
        # PaymentRecord has no version/updated_at (PRD §2.4)
        record["id"] = db.new_id()
        record["created_at"] = iso_format(db.now())
        db.payment_records[record["id"]] = record

        # 3. Update bill paid_amount and re-derive status
        new_paid = round2_dec(to_decimal(bill.get("paid_amount", 0)) + amt)
        bill["paid_amount"] = float(new_paid)

        prior_status = bill.get("status")
        now = db.now()
        due_date = parse_iso(bill["due_date"], field="due_date")

        if new_paid >= total_due:
            # Transition to PAID from any non-terminal state
            bill["status"] = "PAID"
            # Freeze late fee at the value computed against the reconciliation instant
            refresh_late_fee(bill, evaluation_instant=paid_at)
            bill["dunning_stage"] = "NONE"
        elif new_paid > 0:
            if prior_status == "OPEN" and now <= due_date:
                bill["status"] = "PARTIALLY_PAID"
            elif prior_status == "OVERDUE":
                bill["status"] = "PARTIALLY_PAID"
                refresh_late_fee(bill, evaluation_instant=paid_at)
            elif prior_status == "OPEN" and now > due_date:
                # Per PRD: "partial payments arriving after the due date are
                # recognized but the bill remains OVERDUE". OPEN past-due → OVERDUE.
                bill["status"] = "OVERDUE"
                refresh_late_fee(bill, evaluation_instant=now)
                if bill.get("dunning_stage") == "NONE":
                    bill["dunning_stage"] = "REMINDED"

        bump(bill)

        prop = db.properties.get(bill.get("property_id"))
        if prop is not None:
            recompute_for_owner(prop.get("owner_id"))

        return record
