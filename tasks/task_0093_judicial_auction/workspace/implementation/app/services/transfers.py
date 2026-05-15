"""TransferOrder lifecycle — PRD §3.11."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..audit import emit_audit, emit_system_audit
from ..clock import now_dt, parse_iso
from ..constants import ASSET_PROFILE_TO_AGENCY, HANDOVER_BUFFER_HOURS
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store


def create_transfer_order(body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    confirmation_id = body.get("confirmation_id")
    if not isinstance(confirmation_id, str) or not confirmation_id.strip():
        raise ApiError("ERR_VALIDATION", "confirmation_id must be a non-empty string.")
    handover_scheduled_at = body.get("handover_scheduled_at")
    if not isinstance(handover_scheduled_at, str) or not handover_scheduled_at.strip():
        raise ApiError("ERR_VALIDATION", "handover_scheduled_at must be a non-empty string.")
    transfer_uri = body.get("transfer_instrument_uri")
    if not isinstance(transfer_uri, str) or not transfer_uri.strip():
        raise ApiError("ERR_VALIDATION", "transfer_instrument_uri must be a non-empty string.")
    tenancy_cleared = bool(body.get("tenancy_cleared") or False)

    confirmation = store.confirmations.get(confirmation_id)
    if confirmation is None:
        raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")

    # Uniqueness on confirmation_id
    for t in store.transfer_orders.values():
        if t.get("confirmation_id") == confirmation_id:
            raise ApiError("ERR_DUPLICATE", "TransferOrder already exists for this confirmation.")

    auction = store.auctions.get(confirmation["auction_id"])
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", "Parent auction not found.")
    lot = store.lots.get(auction["lot_id"])
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", "Parent lot not found.")

    asset_profile = lot["asset_profile"]
    counterpart_agency = ASSET_PROFILE_TO_AGENCY.get(asset_profile)
    if counterpart_agency is None:
        raise ApiError("ERR_VALIDATION", f"Unknown asset_profile: {asset_profile}.")

    try:
        handover_dt = parse_iso(handover_scheduled_at)
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))

    # Handover buffer: same-day handovers on same counterpart_agency must be >= 4h apart
    handover_date = handover_dt.date()
    for t in store.transfer_orders.values():
        if t.get("counterpart_agency") != counterpart_agency:
            continue
        try:
            existing_dt = parse_iso(t["handover_scheduled_at"])
        except (KeyError, ValueError):
            continue
        if existing_dt.date() != handover_date:
            continue
        gap = abs((handover_dt - existing_dt).total_seconds())
        if gap < HANDOVER_BUFFER_HOURS * 3600:
            raise ApiError(
                "ERR_HANDOVER_AGENCY_BUSY",
                "Another handover within the agency buffer window.",
            )

    cf = common_fields_create()
    transfer = {
        **cf,
        "confirmation_id": confirmation_id,
        "counterpart_agency": counterpart_agency,
        "handover_scheduled_at": handover_scheduled_at,
        "transfer_instrument_uri": transfer_uri,
        "tenancy_cleared": tenancy_cleared,
        "status": "INITIATED",
        "blocked_reason": None,
    }
    store.transfer_orders[transfer["id"]] = transfer
    return transfer


def notify_agency(transfer_id: str) -> dict[str, Any]:
    store = get_store()
    transfer = store.transfer_orders.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_id} not found.")
    if transfer["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE", f"TransferOrder not in INITIATED (got {transfer['status']}).")

    confirmation = store.confirmations.get(transfer["confirmation_id"])
    if confirmation is None:
        raise ApiError("ERR_NOT_FOUND", "Parent confirmation not found.")
    if confirmation["status"] not in {"ISSUED", "SEALED"}:
        raise ApiError("ERR_INVALID_STATE", "Confirmation must be ISSUED or SEALED.")

    payment = None
    for p in store.payments.values():
        if p.get("confirmation_id") == confirmation["id"]:
            payment = p
            break
    if payment is None or payment.get("status") != "PAID":
        raise ApiError("ERR_INVALID_STATE", "Payment must be PAID before notifying agency.")
    if not transfer.get("transfer_instrument_uri"):
        raise ApiError("ERR_VALIDATION", "transfer_instrument_uri must be non-empty.")

    transfer["status"] = "AGENCY_NOTIFIED"
    bump_version(transfer)
    emit_audit(
        "TRANSFER_NOTIFIED",
        subject_entity="TransferOrder",
        subject_id=transfer_id,
        payload={"counterpart_agency": transfer["counterpart_agency"]},
    )
    return transfer


def complete_handover(transfer_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    transfer = store.transfer_orders.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_id} not found.")
    if transfer["status"] != "AGENCY_NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", f"TransferOrder not in AGENCY_NOTIFIED (got {transfer['status']}).")

    if "tenancy_cleared" in body and body["tenancy_cleared"] is not None:
        if not isinstance(body["tenancy_cleared"], bool):
            raise ApiError("ERR_VALIDATION", "tenancy_cleared must be boolean.")
        transfer["tenancy_cleared"] = bool(body["tenancy_cleared"])

    try:
        scheduled_dt = parse_iso(transfer["handover_scheduled_at"])
    except ValueError:
        raise ApiError("ERR_VALIDATION", "handover_scheduled_at invalid.")
    if now_dt() < scheduled_dt:
        raise ApiError("ERR_INVALID_STATE", "Cannot complete handover before handover_scheduled_at.")

    # REAL_ESTATE requires tenancy_cleared
    confirmation = store.confirmations.get(transfer["confirmation_id"])
    auction = store.auctions.get(confirmation["auction_id"]) if confirmation else None
    lot = store.lots.get(auction["lot_id"]) if auction else None
    if lot and lot["asset_profile"] == "REAL_ESTATE" and not transfer.get("tenancy_cleared"):
        raise ApiError("ERR_TENANCY_NOT_CLEARED", "Tenancy must be cleared for REAL_ESTATE handover.")

    transfer["status"] = "HANDOVER_DONE"
    bump_version(transfer)
    return transfer


def confirm_completion(transfer_id: str) -> dict[str, Any]:
    store = get_store()
    transfer = store.transfer_orders.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_id} not found.")
    if transfer["status"] != "HANDOVER_DONE":
        raise ApiError("ERR_INVALID_STATE", f"TransferOrder not in HANDOVER_DONE (got {transfer['status']}).")

    transfer["status"] = "COMPLETED"
    bump_version(transfer)
    emit_audit(
        "TRANSFER_COMPLETED",
        subject_entity="TransferOrder",
        subject_id=transfer_id,
        payload={},
    )

    # Bubble parent Lot.status to TRANSFERRED
    confirmation = store.confirmations.get(transfer["confirmation_id"])
    if confirmation:
        auction = store.auctions.get(confirmation["auction_id"])
        if auction:
            lot = store.lots.get(auction["lot_id"])
            if lot:
                lot["status"] = "TRANSFERRED"
                bump_version(lot)

    return transfer


def block_transfer(transfer_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    transfer = store.transfer_orders.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_id} not found.")
    if transfer["status"] != "AGENCY_NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", f"TransferOrder not in AGENCY_NOTIFIED (got {transfer['status']}).")
    blocked_reason = body.get("blocked_reason")
    if not isinstance(blocked_reason, str) or not blocked_reason.strip():
        raise ApiError("ERR_VALIDATION", "blocked_reason must be a non-empty string.")

    transfer["status"] = "BLOCKED"
    transfer["blocked_reason"] = blocked_reason
    bump_version(transfer)
    return transfer
