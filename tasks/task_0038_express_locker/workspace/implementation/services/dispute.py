"""Dispute lifecycle: open, resolve (WAIVE / REJECT / COURIER_AT_FAULT)."""

from clock import iso, now
from db import DB, new_id
from errors import APIError, invalid_request, not_found
from services.audit import append_audit
from services.courier import maybe_auto_blacklist
from services.fee import latest_fee
from services.util import (
    stamp_create,
    stamp_update,
    require_field,
    opt_field,
    check_version,
)


CLAIM_TYPES = {"WRONG_DEPOSIT", "OVERTIME_DISPUTE", "DAMAGED"}
RESOLUTIONS = {"WAIVE", "REJECT", "COURIER_AT_FAULT"}


def get_dispute(disp_id: str):
    d = DB.disputes.get(disp_id)
    if not d:
        raise not_found(f"Dispute not found: {disp_id}")
    return d


def serialize_dispute(d: dict) -> dict:
    return {
        "id": d["id"],
        "parcel_id": d.get("parcel_id"),
        "opened_by_role": d.get("opened_by_role"),
        "claim_type": d.get("claim_type"),
        "status": d.get("status"),
        "outcome_amount_cents": d.get("outcome_amount_cents", 0),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
        "version": d.get("version", 0),
    }


def open_dispute(parcel_id: str, payload: dict, role: str, actor_id: str) -> dict:
    parcel = DB.parcels.get(parcel_id)
    if not parcel:
        raise not_found(f"Parcel not found: {parcel_id}")
    claim_type = require_field(payload, "claim_type")
    if claim_type not in CLAIM_TYPES:
        raise invalid_request(f"claim_type must be one of {sorted(CLAIM_TYPES)}")
    rid = new_id()
    base = stamp_create()
    record = {
        "id": rid,
        "parcel_id": parcel_id,
        "opened_by_role": role if role in ("Recipient", "Courier") else "Recipient",
        "claim_type": claim_type,
        "status": "OPEN",
        "outcome_amount_cents": 0,
        **base,
    }
    DB.disputes[rid] = record
    return record


def resolve_dispute(disp_id: str, payload: dict, actor_id: str) -> dict:
    d = get_dispute(disp_id)
    check_version(d, opt_field(payload, "version"))

    if d.get("status") != "OPEN":
        raise APIError("ERR_DISPUTE_ALREADY_RESOLVED",
                       f"Dispute already in {d.get('status')}", 409)

    resolution = require_field(payload, "resolution")
    if resolution not in RESOLUTIONS:
        raise invalid_request(f"resolution must be one of {sorted(RESOLUTIONS)}")

    parcel = DB.parcels.get(d.get("parcel_id"))
    if not parcel:
        raise not_found("Linked parcel missing")

    if resolution == "REJECT":
        d["status"] = "RESOLVED_REJECTED"
        d["outcome_amount_cents"] = 0
        stamp_update(d)
        append_audit("OperationsAdmin", actor_id, "FEE_ADJUSTMENT", "Dispute", d["id"],
                     {"resolution": "REJECT"})
        return d

    if resolution == "WAIVE":
        if parcel.get("status") in ("DISPOSED", "RETURNED"):
            raise APIError("ERR_INVALID_REQUEST",
                           f"Cannot WAIVE on {parcel.get('status')} parcel", 400)
        fee = latest_fee(parcel["id"])
        amt = 0
        if fee:
            if fee.get("payment_status") == "PAID":
                fee["payment_status"] = "REFUNDED"
                stamp_update(fee)
                amt = fee.get("amount_cents", 0)
            elif fee.get("payment_status") == "UNPAID":
                fee["payment_status"] = "WAIVED"
                stamp_update(fee)
                amt = fee.get("amount_cents", 0)
        parcel["fee_waived"] = True
        parcel["fee_waiver_reason"] = "MANUAL_DISPUTE"
        stamp_update(parcel)
        d["status"] = "RESOLVED_WAIVED"
        d["outcome_amount_cents"] = amt
        stamp_update(d)
        append_audit("OperationsAdmin", actor_id, "FEE_ADJUSTMENT", "Dispute", d["id"],
                     {"resolution": "WAIVE", "amount_cents": amt})
        return d

    # COURIER_AT_FAULT
    fee = latest_fee(parcel["id"])
    amt = 0
    if fee:
        if fee.get("payment_status") == "PAID":
            fee["payment_status"] = "REFUNDED"
            stamp_update(fee)
            amt = fee.get("amount_cents", 0)
        elif fee.get("payment_status") == "UNPAID":
            fee["payment_status"] = "WAIVED"
            stamp_update(fee)
            amt = fee.get("amount_cents", 0)
    parcel["fee_waived"] = True
    parcel["fee_waiver_reason"] = "MANUAL_DISPUTE"
    stamp_update(parcel)
    d["status"] = "RESOLVED_COURIER_AT_FAULT"
    d["outcome_amount_cents"] = amt
    stamp_update(d)
    append_audit("OperationsAdmin", actor_id, "FEE_ADJUSTMENT", "Dispute", d["id"],
                 {"resolution": "COURIER_AT_FAULT", "amount_cents": amt})
    # Cascade: complaint_count is computed on read; check whether courier should now be blacklisted
    courier_id = parcel.get("courier_id")
    if courier_id:
        maybe_auto_blacklist(courier_id, "system", "system")
    return d
