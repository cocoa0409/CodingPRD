"""Confirmation lifecycle (DRAFT → ISSUED/FAILED → SEALED) — PRD §3.8."""
from __future__ import annotations

from typing import Any

from ..audit import emit_audit, emit_system_audit
from ..clock import add_days, format_iso, now_dt
from ..constants import COLLUSION_BLOCK_THRESHOLD
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso


def create_confirmation(body: dict[str, Any]) -> dict[str, Any]:
    """POST /confirmations — create DRAFT confirmation."""
    store = get_store()
    auction_id = body.get("auction_id")
    if not isinstance(auction_id, str) or not auction_id.strip():
        raise ApiError("ERR_VALIDATION", "auction_id must be a non-empty string.")
    ruling_uri = body.get("ruling_document_uri")
    if not isinstance(ruling_uri, str) or not ruling_uri.strip():
        raise ApiError("ERR_VALIDATION", "ruling_document_uri must be a non-empty string.")
    use_second = bool(body.get("use_second_bidder") or False)

    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")

    # Must be SOLD
    if auction["status"] != "SOLD":
        raise ApiError("ERR_INVALID_STATE", f"Auction must be SOLD (got {auction['status']}).")

    # Empty-bid-set guard
    if auction.get("current_high_cents") is None:
        raise ApiError("ERR_NO_VALID_BIDS", "Auction has no VALID bids.")

    # Resolve winning_bid_id
    if use_second:
        bid_id = auction.get("second_highest_bid_id")
        if not bid_id:
            raise ApiError("ERR_NO_ELIGIBLE_SECOND_BIDDER", "No second-highest bid available.")
        bid = store.bids.get(bid_id)
        if bid is None:
            raise ApiError("ERR_NO_ELIGIBLE_SECOND_BIDDER", "Second-highest bid not found.")
        acct = store.bidder_accounts.get(bid.get("bidder_account_id"))
        if acct is None or acct.get("status") != "ACTIVE":
            raise ApiError("ERR_NO_ELIGIBLE_SECOND_BIDDER", "Second-highest bidder not ACTIVE.")
    else:
        bid_id = auction.get("highest_bid_id")
        if not bid_id:
            raise ApiError("ERR_NO_VALID_BIDS", "Auction has no highest VALID bid.")

    # Uniqueness on auction_id where status != FAILED
    for c in store.confirmations.values():
        if c.get("auction_id") == auction_id and c.get("status") != "FAILED":
            raise ApiError("ERR_DUPLICATE", "Confirmation already exists for this auction.")

    cf = common_fields_create()
    confirmation = {
        **cf,
        "auction_id": auction_id,
        "winning_bid_id": bid_id,
        "ruling_document_uri": ruling_uri,
        "status": "DRAFT",
        "issued_at": None,
        "sealed_at": None,
        "failure_reason": None,
        "use_second_bidder": use_second,
    }
    store.confirmations[confirmation["id"]] = confirmation
    return confirmation


def issue_confirmation(confirmation_id: str) -> dict[str, Any]:
    from .payments import create_payment_for_confirmation

    store = get_store()
    confirmation = store.confirmations.get(confirmation_id)
    if confirmation is None:
        raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")
    if confirmation["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", f"Confirmation not in DRAFT (got {confirmation['status']}).")

    auction = store.auctions.get(confirmation["auction_id"])
    if auction is None or auction["status"] != "SOLD":
        raise ApiError("ERR_INVALID_STATE", "Auction must be SOLD.")

    bid_id = confirmation["winning_bid_id"]
    use_second = bool(confirmation.get("use_second_bidder"))
    if use_second:
        expected_bid = auction.get("second_highest_bid_id")
    else:
        expected_bid = auction.get("highest_bid_id")
    if bid_id != expected_bid:
        raise ApiError("ERR_INVALID_STATE", "winning_bid_id no longer matches Auction.highest_bid_id.")

    bid = store.bids.get(bid_id)
    if bid is None:
        raise ApiError("ERR_NOT_FOUND", "Winning bid not found.")
    account = store.bidder_accounts.get(bid["bidder_account_id"])
    if account is None:
        raise ApiError("ERR_NOT_FOUND", "Winning bidder account not found.")
    if account["status"] == "BLOCKED" or int(account.get("collusion_risk_score") or 0) >= COLLUSION_BLOCK_THRESHOLD:
        raise ApiError("ERR_WINNER_DISQUALIFIED", "Winner is BLOCKED or risk-score too high.")
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_WINNER_DISQUALIFIED", "Winner is not ACTIVE.")
    if not confirmation.get("ruling_document_uri"):
        raise ApiError("ERR_VALIDATION", "ruling_document_uri must be non-empty.")

    confirmation["status"] = "ISSUED"
    confirmation["issued_at"] = now_iso()
    bump_version(confirmation)
    emit_audit(
        "CONFIRMATION_ISSUED",
        subject_entity="Confirmation",
        subject_id=confirmation_id,
        payload={"auction_id": confirmation["auction_id"], "winning_bid_id": bid_id},
    )

    # Need to set outcome_winner_account_id on auction if not yet (use_second case)
    if use_second:
        auction["outcome_winner_account_id"] = bid["bidder_account_id"]
        bump_version(auction)

    # Cascade: Payment row creation
    create_payment_for_confirmation(confirmation)

    return confirmation


def fail_confirmation(confirmation_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from .deposits import forfeit_winner_deposit
    from .lots import trigger_reauction

    store = get_store()
    confirmation = store.confirmations.get(confirmation_id)
    if confirmation is None:
        raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")
    if confirmation["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", f"Confirmation not in DRAFT (got {confirmation['status']}).")
    failure_reason = body.get("failure_reason")
    if failure_reason not in {"COLLUSION_FOUND", "BIDDER_DISQUALIFIED", "COURT_OVERRIDE"}:
        raise ApiError(
            "ERR_VALIDATION",
            "failure_reason must be COLLUSION_FOUND, BIDDER_DISQUALIFIED, or COURT_OVERRIDE.",
        )
    auction = store.auctions.get(confirmation["auction_id"])
    if auction is None or auction["status"] != "SOLD":
        raise ApiError("ERR_INVALID_STATE", "Auction must be SOLD.")

    confirmation["status"] = "FAILED"
    confirmation["failure_reason"] = failure_reason
    bump_version(confirmation)
    emit_audit(
        "CONFIRMATION_FAILED",
        subject_entity="Confirmation",
        subject_id=confirmation_id,
        payload={"failure_reason": failure_reason},
    )

    # Forfeit winner's deposit on collusion or disqualification
    if failure_reason in {"COLLUSION_FOUND", "BIDDER_DISQUALIFIED"}:
        winner_id = auction.get("outcome_winner_account_id")
        if winner_id:
            forfeit_winner_deposit(confirmation["auction_id"], winner_id)

    # Trigger re-auction (may raise ERR_REAUCTION_LIMIT_REACHED — cap then swallowed)
    try:
        trigger_reauction(auction["lot_id"], reason="CONFIRMATION_FAILED")
    except ApiError as exc:
        if exc.error_id != "ERR_REAUCTION_LIMIT_REACHED":
            raise
        # When the round-3 cap is hit the confirmation still fails; lot stays closed.

    return confirmation


def seal_confirmation(confirmation_id: str) -> dict[str, Any]:
    store = get_store()
    confirmation = store.confirmations.get(confirmation_id)
    if confirmation is None:
        raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")
    if confirmation["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", f"Confirmation not in ISSUED (got {confirmation['status']}).")
    # Payment.status = PAID
    payment = None
    for p in store.payments.values():
        if p.get("confirmation_id") == confirmation_id:
            payment = p
            break
    if payment is None or payment.get("status") != "PAID":
        raise ApiError("ERR_INVALID_STATE", "Payment must be PAID to seal.")
    # TransferOrder exists with status != BLOCKED
    transfer = None
    for t in store.transfer_orders.values():
        if t.get("confirmation_id") == confirmation_id:
            transfer = t
            break
    if transfer is None or transfer.get("status") == "BLOCKED":
        raise ApiError("ERR_INVALID_STATE", "TransferOrder must exist and not be BLOCKED to seal.")

    confirmation["status"] = "SEALED"
    confirmation["sealed_at"] = now_iso()
    bump_version(confirmation)
    emit_audit(
        "CONFIRMATION_SEALED",
        subject_entity="Confirmation",
        subject_id=confirmation_id,
        payload={},
    )
    return confirmation
