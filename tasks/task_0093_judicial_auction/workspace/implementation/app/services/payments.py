"""Payment lifecycle: creation, settle, extend, forfeit, penalty accrual — PRD §3.9."""
from __future__ import annotations

import random
import string
from datetime import timedelta
from typing import Any

from ..audit import emit_audit, emit_system_audit
from ..clock import format_iso, now_dt, parse_iso
from ..constants import GRACE_FORFEITURE_DAYS
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso
from .calculations import balance_due, days_overdue as _days_overdue, late_payment_penalty


def _mint_receipt_no() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "RCPT_" + "".join(random.choices(alphabet, k=12))


def create_payment_for_confirmation(confirmation: dict[str, Any]) -> dict[str, Any]:
    """Spawned on Confirmation.DRAFT→ISSUED."""
    store = get_store()
    auction = store.auctions.get(confirmation["auction_id"])
    if auction is None:
        raise ApiError("ERR_INVALID_STATE", "Auction missing for confirmation.")
    winner_id = auction.get("outcome_winner_account_id")
    if winner_id is None:
        # In the use_second path the auction.outcome_winner_account_id is set in
        # issue_confirmation before calling here.
        raise ApiError("ERR_INVALID_STATE", "Auction.outcome_winner_account_id not set.")

    # Find matched deposit
    matched = None
    for dep in store.deposits.values():
        if (
            dep.get("auction_id") == auction["id"]
            and dep.get("bidder_account_id") == winner_id
            and dep.get("status") == "PAID"
        ):
            matched = dep
            break

    winning_bid = store.bids.get(confirmation["winning_bid_id"])
    if winning_bid is None:
        raise ApiError("ERR_INVALID_STATE", "Winning bid missing.")
    winning_amount = int(winning_bid["amount_cents"])
    deposit_amount = int(matched["amount_cents"]) if matched else 0

    balance = balance_due(winning_amount, deposit_amount)
    cf = common_fields_create()
    due_dt = now_dt() + timedelta(days=int(auction["payment_deadline_days"]))
    payment = {
        **cf,
        "confirmation_id": confirmation["id"],
        "balance_due_cents": int(balance),
        "penalty_accrued_cents": 0,
        "amount_paid_cents": 0,
        "status": "PENDING",
        "due_at": format_iso(due_dt),
        "receipt_no": None,
    }
    # Edge case: balance == 0 → auto-PAID
    if balance == 0:
        payment["status"] = "PAID"
        payment["receipt_no"] = _mint_receipt_no()
    store.payments[payment["id"]] = payment
    return payment


def _refresh_penalty(payment: dict[str, Any]) -> None:
    """Recompute penalty_accrued_cents based on current clock. Idempotent."""
    if payment.get("status") in {"PENDING", "PAID", "FORFEITED"}:
        # PENDING/PAID: zero accrual per PRD; FORFEITED: freeze
        if payment["status"] != "FORFEITED":
            payment["penalty_accrued_cents"] = 0
        return
    if payment["status"] == "OVERDUE":
        try:
            due_dt = parse_iso(payment["due_at"])
        except (KeyError, ValueError):
            return
        days = _days_overdue(now_dt(), due_dt)
        payment["penalty_accrued_cents"] = late_payment_penalty(
            int(payment["balance_due_cents"]), days
        )


def get_payment_for_read(payment_id: str) -> dict[str, Any]:
    """Read endpoint: recomputes penalty_accrued_cents on every read."""
    store = get_store()
    payment = store.payments.get(payment_id)
    if payment is None:
        raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
    _refresh_penalty(payment)
    return payment


def settle_payment(payment_id: str, body: dict[str, Any], caller_id: str) -> dict[str, Any]:
    store = get_store()
    payment = store.payments.get(payment_id)
    if payment is None:
        raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")

    # Ownership: Bidder must own winning bidder account
    confirmation = store.confirmations.get(payment["confirmation_id"])
    if confirmation:
        auction = store.auctions.get(confirmation["auction_id"])
        if auction and auction.get("outcome_winner_account_id") != caller_id:
            raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may settle only their own payment.")

    if payment["status"] == "FORFEITED":
        raise ApiError("ERR_PAYMENT_FORFEITED", "Cannot settle a FORFEITED payment.")
    if payment["status"] not in {"PENDING", "OVERDUE"}:
        raise ApiError("ERR_INVALID_STATE", f"Cannot settle in status {payment['status']}.")

    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ApiError("ERR_VALIDATION", "amount_cents must be a non-negative integer.")

    _refresh_penalty(payment)
    required = int(payment["balance_due_cents"]) + int(payment["penalty_accrued_cents"])
    incoming_total = int(payment["amount_paid_cents"]) + int(amount)
    if incoming_total < required:
        raise ApiError(
            "ERR_PARTIAL_PAYMENT_REJECTED",
            f"Payment {amount} insufficient — total {incoming_total} < required {required}.",
        )

    payment["amount_paid_cents"] = incoming_total
    payment["status"] = "PAID"
    payment["receipt_no"] = _mint_receipt_no()
    bump_version(payment)
    emit_audit(
        "PAYMENT_RECEIVED",
        subject_entity="Payment",
        subject_id=payment_id,
        payload={"amount_cents": amount, "total_paid_cents": incoming_total},
    )
    return payment


def extend_payment(payment_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    payment = store.payments.get(payment_id)
    if payment is None:
        raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
    if payment["status"] != "OVERDUE":
        raise ApiError("ERR_INVALID_STATE", "Payment must be OVERDUE to extend.")
    extension_days = body.get("extension_days")
    if isinstance(extension_days, bool) or not isinstance(extension_days, int):
        raise ApiError("ERR_VALIDATION", "extension_days must be an integer.")
    if extension_days < 1 or extension_days > 14:
        raise ApiError("ERR_VALIDATION", "extension_days must be in [1, 14].")

    new_due = now_dt() + timedelta(days=extension_days)
    payment["due_at"] = format_iso(new_due)
    payment["status"] = "PENDING"
    # Penalty accrued retained
    bump_version(payment)
    return payment


def forfeit_payment(payment_id: str) -> dict[str, Any]:
    from .deposits import forfeit_winner_deposit
    from .lots import trigger_reauction

    store = get_store()
    payment = store.payments.get(payment_id)
    if payment is None:
        raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
    if payment["status"] != "OVERDUE":
        raise ApiError("ERR_INVALID_STATE", "Payment must be OVERDUE to forfeit.")
    try:
        due_dt = parse_iso(payment["due_at"])
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Payment.due_at invalid.")
    if now_dt() <= due_dt + timedelta(days=GRACE_FORFEITURE_DAYS):
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Must wait at least {GRACE_FORFEITURE_DAYS} days past due_at to forfeit.",
        )

    payment["status"] = "FORFEITED"
    bump_version(payment)

    # Cascade winner deposit forfeit + re-auction
    confirmation = store.confirmations.get(payment["confirmation_id"])
    if confirmation:
        auction = store.auctions.get(confirmation["auction_id"])
        if auction:
            winner_id = auction.get("outcome_winner_account_id")
            if winner_id:
                forfeit_winner_deposit(confirmation["auction_id"], winner_id)
            try:
                trigger_reauction(auction["lot_id"], reason="PAYMENT_FORFEITED")
            except ApiError:
                # ERR_REAUCTION_LIMIT_REACHED — Lot stays AUCTIONED (closed)
                pass

    return payment


def sweep_overdue_payments() -> None:
    """Drive PENDING → OVERDUE when now > due_at."""
    store = get_store()
    for p in store.payments.values():
        if p.get("status") != "PENDING":
            continue
        try:
            due_dt = parse_iso(p["due_at"])
        except (KeyError, ValueError):
            continue
        if now_dt() > due_dt:
            p["status"] = "OVERDUE"
            bump_version(p)
            emit_system_audit(
                "PAYMENT_OVERDUE",
                subject_entity="Payment",
                subject_id=p["id"],
                payload={"due_at": p["due_at"]},
            )
