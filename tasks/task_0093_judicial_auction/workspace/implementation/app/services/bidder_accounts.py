"""BidderAccount registration, clearance, and collusion-driven transitions."""
from __future__ import annotations

import math
from typing import Any

from ..audit import emit_system_audit
from ..clock import now_dt, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store


def create_bidder_account(body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    real_name = body.get("real_name")
    if not isinstance(real_name, str) or not real_name.strip():
        raise ApiError("ERR_VALIDATION", "real_name must be a non-empty string.")
    id_doc = body.get("id_document_no")
    if not isinstance(id_doc, str) or not id_doc.strip():
        raise ApiError("ERR_VALIDATION", "id_document_no must be a non-empty string.")
    ip_fingerprint = body.get("ip_fingerprint", "")
    if ip_fingerprint is not None and not isinstance(ip_fingerprint, str):
        raise ApiError("ERR_VALIDATION", "ip_fingerprint must be a string.")

    # Uniqueness on id_document_no where status = ACTIVE
    for acc in store.bidder_accounts.values():
        if acc.get("id_document_no") == id_doc and acc.get("status") == "ACTIVE":
            raise ApiError("ERR_DUPLICATE", f"id_document_no already exists: {id_doc}")

    cf = common_fields_create()
    account = {
        **cf,
        "real_name": real_name,
        "id_document_no": id_doc,
        "ip_fingerprint": ip_fingerprint or "",
        "account_age_days": 0,
        "status": "ACTIVE",
        "collusion_risk_score": 0,
    }
    store.bidder_accounts[account["id"]] = account
    return _augment_account_age(account)


def _augment_account_age(account: dict[str, Any]) -> dict[str, Any]:
    """Recompute account_age_days from created_at relative to current clock."""
    try:
        created = parse_iso(account["created_at"])
    except Exception:  # noqa: BLE001
        return account
    delta = now_dt() - created
    seconds = max(0.0, delta.total_seconds())
    account["account_age_days"] = int(math.floor(seconds / 86400.0))
    return account


def get_account(account_id: str) -> dict[str, Any]:
    store = get_store()
    account = store.bidder_accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", f"BidderAccount {account_id} not found.")
    return _augment_account_age(account)


def clear_account(account_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    account = store.bidder_accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", f"BidderAccount {account_id} not found.")
    if account["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only SUSPENDED accounts can be cleared.")
    resolved = body.get("investigation_resolved")
    if resolved is not True:
        raise ApiError("ERR_VALIDATION", "investigation_resolved must be true.")
    account["status"] = "ACTIVE"
    bump_version(account)
    return _augment_account_age(account)


def apply_collusion_outcome(account_id: str, score: int) -> None:
    """Apply COLLUSION threshold transitions per PRD §3.6.

    ACTIVE → SUSPENDED when 60 <= score <= 79.
    ACTIVE → BLOCKED when score >= 80.
    SUSPENDED → BLOCKED when score >= 80.
    """
    from ..constants import COLLUSION_BLOCK_THRESHOLD, COLLUSION_SUSPECT_THRESHOLD

    store = get_store()
    account = store.bidder_accounts.get(account_id)
    if account is None:
        return
    account["collusion_risk_score"] = int(score)
    prior_status = account["status"]
    new_status = prior_status

    if score >= COLLUSION_BLOCK_THRESHOLD:
        if prior_status != "BLOCKED":
            new_status = "BLOCKED"
    elif score >= COLLUSION_SUSPECT_THRESHOLD:
        if prior_status == "ACTIVE":
            new_status = "SUSPENDED"

    if new_status != prior_status:
        account["status"] = new_status
        bump_version(account)
        emit_system_audit(
            "COLLUSION_FLAGGED",
            subject_entity="BidderAccount",
            subject_id=account_id,
            payload={"prior_status": prior_status, "new_status": new_status, "score": score},
        )
        if new_status == "BLOCKED":
            _rollback_open_bids(account_id)
    else:
        bump_version(account)


def _rollback_open_bids(account_id: str) -> None:
    """When account becomes BLOCKED: roll back the bidder's VALID bids on LIVE auctions."""
    from .auctions import recompute_high_from_bids
    from ..audit import emit_system_audit

    store = get_store()
    affected_auctions: set[str] = set()
    for bid in store.bids.values():
        if bid.get("bidder_account_id") != account_id:
            continue
        if bid.get("validity") != "VALID":
            continue
        auction = store.auctions.get(bid.get("auction_id"))
        if auction is None or auction.get("status") != "LIVE":
            continue
        bid["validity"] = "ROLLED_BACK"
        affected_auctions.add(bid["auction_id"])
        emit_system_audit(
            "BID_ROLLED_BACK",
            subject_entity="Bid",
            subject_id=bid["id"],
            payload={"reason": "ACCOUNT_BLOCKED", "auction_id": bid["auction_id"]},
        )
    for auction_id in affected_auctions:
        recompute_high_from_bids(auction_id)
