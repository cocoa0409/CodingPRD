"""Deposit lifecycle: post, pay, dispute, resolve, cascade refund/forfeit — PRD §3.4 / §3.10."""
from __future__ import annotations

from typing import Any

from ..audit import emit_audit, emit_system_audit
from ..clock import add_hours, format_iso, now_dt, parse_iso
from ..constants import REFUND_SLA_HOURS
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso


def post_deposit(body: dict[str, Any], caller_role: str, caller_id: str) -> dict[str, Any]:
    """POST /deposits — create PENDING deposit."""
    store = get_store()
    auction_id = body.get("auction_id")
    bidder_account_id = body.get("bidder_account_id")
    if not isinstance(auction_id, str) or not auction_id.strip():
        raise ApiError("ERR_VALIDATION", "auction_id must be a non-empty string.")
    if not isinstance(bidder_account_id, str) or not bidder_account_id.strip():
        raise ApiError("ERR_VALIDATION", "bidder_account_id must be a non-empty string.")

    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
    account = store.bidder_accounts.get(bidder_account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", f"BidderAccount {bidder_account_id} not found.")

    # Bidder ownership: a Bidder posting a deposit must own the BidderAccount.
    if caller_role == "Bidder" and caller_id != bidder_account_id:
        raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may post deposits only for their own account.")

    # Deposit amount must be pinned on auction
    if auction.get("deposit_amount_cents") is None:
        raise ApiError("ERR_INVALID_STATE", "Auction.deposit_amount_cents not pinned (announce first).")

    # Uniqueness on (auction_id, bidder_account_id)
    for dep in store.deposits.values():
        if (
            dep.get("auction_id") == auction_id
            and dep.get("bidder_account_id") == bidder_account_id
        ):
            raise ApiError(
                "ERR_DEPOSIT_DUPLICATE",
                "Duplicate deposit for (auction_id, bidder_account_id).",
            )

    cf = common_fields_create()
    deposit = {
        **cf,
        "auction_id": auction_id,
        "bidder_account_id": bidder_account_id,
        "amount_cents": int(auction["deposit_amount_cents"]),
        "status": "PENDING",
        "paid_at": None,
        "refunded_at": None,
        "refund_due_at": None,
        "dispute_opened_at": None,
    }
    store.deposits[deposit["id"]] = deposit
    return deposit


def pay_deposit(deposit_id: str, caller_role: str, caller_id: str) -> dict[str, Any]:
    """POST /deposits/{id}/pay — PENDING → PAID."""
    store = get_store()
    deposit = store.deposits.get(deposit_id)
    if deposit is None:
        raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")

    # Ownership for Bidder
    if caller_role == "Bidder" and caller_id != deposit.get("bidder_account_id"):
        raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may pay only their own deposit.")

    if deposit["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", f"Deposit not in PENDING status (got {deposit['status']}).")

    auction = store.auctions.get(deposit["auction_id"])
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {deposit['auction_id']} not found.")

    if auction["status"] not in {"SCHEDULED", "LIVE"}:
        raise ApiError("ERR_INVALID_STATE", "Deposit can only be paid while auction is SCHEDULED or LIVE.")

    account = store.bidder_accounts.get(deposit["bidder_account_id"])
    if account is None:
        raise ApiError("ERR_NOT_FOUND", "BidderAccount not found.")
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_BIDDER_NOT_ACTIVE", "BidderAccount must be ACTIVE.")

    try:
        deadline = parse_iso(auction["deposit_deadline_at"])
    except (KeyError, ValueError):
        raise ApiError("ERR_VALIDATION", "Auction.deposit_deadline_at missing or invalid.")
    if now_dt() > deadline:
        raise ApiError("ERR_DEPOSIT_DEADLINE_PASSED", "Deposit deadline has elapsed.")

    deposit["status"] = "PAID"
    deposit["paid_at"] = now_iso()
    bump_version(deposit)
    emit_audit(
        "DEPOSIT_PAID",
        subject_entity="Deposit",
        subject_id=deposit_id,
        payload={"auction_id": deposit["auction_id"], "bidder_account_id": deposit["bidder_account_id"]},
    )
    return deposit


def raise_dispute(deposit_id: str, body: dict[str, Any], caller_role: str, caller_id: str) -> dict[str, Any]:
    store = get_store()
    deposit = store.deposits.get(deposit_id)
    if deposit is None:
        raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")

    if caller_role == "Bidder" and caller_id != deposit.get("bidder_account_id"):
        raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may dispute only their own deposit.")

    if deposit["status"] == "REFUNDED":
        raise ApiError("ERR_DEPOSIT_ALREADY_REFUNDED", "Deposit already refunded.")
    if deposit["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", f"Deposit not in PAID status (got {deposit['status']}).")

    refund_due = deposit.get("refund_due_at")
    if not refund_due:
        raise ApiError("ERR_INVALID_STATE", "refund_due_at not set; cannot raise dispute yet.")
    try:
        refund_due_dt = parse_iso(refund_due)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "refund_due_at invalid.")
    if now_dt() <= refund_due_dt:
        raise ApiError("ERR_INVALID_STATE", "Cannot raise dispute before refund_due_at.")

    deposit["status"] = "DISPUTED"
    deposit["dispute_opened_at"] = now_iso()
    bump_version(deposit)
    return deposit


def resolve_dispute(deposit_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    deposit = store.deposits.get(deposit_id)
    if deposit is None:
        raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")
    if deposit["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", f"Deposit not in DISPUTED status (got {deposit['status']}).")

    deposit["status"] = "REFUNDED"
    deposit["refunded_at"] = now_iso()
    bump_version(deposit)
    emit_system_audit(
        "DEPOSIT_REFUNDED",
        subject_entity="Deposit",
        subject_id=deposit_id,
        payload={"resolution_note": body.get("resolution_note") or ""},
    )
    return deposit


def forfeit_winner_deposit(auction_id: str, winner_account_id: str) -> None:
    """Cascade: winner's PAID deposit → FORFEITED (called from payment forfeit /
    confirmation failure with collusion)."""
    store = get_store()
    for dep in store.deposits.values():
        if (
            dep.get("auction_id") == auction_id
            and dep.get("bidder_account_id") == winner_account_id
            and dep.get("status") == "PAID"
        ):
            dep["status"] = "FORFEITED"
            bump_version(dep)
            emit_system_audit(
                "DEPOSIT_FORFEITED",
                subject_entity="Deposit",
                subject_id=dep["id"],
                payload={"auction_id": auction_id, "bidder_account_id": winner_account_id},
            )


def sweep_refunds() -> int:
    """Periodic sweep — refund any PAID deposits on closed auctions whose status is
    still PAID. Returns count of refunded rows."""
    store = get_store()
    refund_due_iso = format_iso(add_hours(now_dt(), REFUND_SLA_HOURS))
    count = 0
    for dep in list(store.deposits.values()):
        if dep.get("status") != "PAID":
            continue
        auction = store.auctions.get(dep.get("auction_id"))
        if auction is None:
            continue
        if auction.get("status") not in {"SOLD", "UNSOLD", "CANCELLED"}:
            continue
        # Skip winner deposits
        if (
            auction.get("status") == "SOLD"
            and dep.get("bidder_account_id") == auction.get("outcome_winner_account_id")
        ):
            continue
        dep["status"] = "REFUNDED"
        dep["refunded_at"] = now_iso()
        if not dep.get("refund_due_at"):
            dep["refund_due_at"] = refund_due_iso
        bump_version(dep)
        emit_system_audit(
            "DEPOSIT_REFUNDED",
            subject_entity="Deposit",
            subject_id=dep["id"],
            payload={"auction_id": dep["auction_id"], "via_sweep": True},
        )
        count += 1
    return count
