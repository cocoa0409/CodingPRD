"""External event ingress: payment_succeeded | payment_refunded | im_delivered | courier_company_ack."""

from db import DB
from errors import APIError, invalid_request, not_found
from services.audit import append_audit
from services.util import stamp_update


SUPPORTED = {"payment_succeeded", "payment_refunded", "im_delivered", "courier_company_ack"}


def emit(payload: dict, actor_role: str, actor_id: str) -> dict:
    if not isinstance(payload, dict):
        raise invalid_request("Body must be an object with event_type and payload")
    event_type = payload.get("event_type")
    body = payload.get("payload") or {}
    if event_type not in SUPPORTED:
        raise invalid_request(f"Unknown event_type: {event_type}")

    if event_type == "payment_succeeded":
        return _handle_payment_succeeded(body, actor_role, actor_id)
    if event_type == "payment_refunded":
        return _handle_payment_refunded(body, actor_role, actor_id)
    # im_delivered / courier_company_ack are recorded for traceability only
    return {"accepted": True, "idempotent": False}


def _handle_payment_succeeded(body: dict, actor_role: str, actor_id: str):
    fee_id = body.get("fee_record_id")
    external_id = body.get("payment_external_id")
    if not fee_id or not external_id:
        raise invalid_request("payment_succeeded requires fee_record_id and payment_external_id")
    rec = DB.fee_records.get(fee_id)
    if not rec:
        raise not_found(f"OvertimeFeeRecord not found: {fee_id}")
    # Idempotency: same external id replay -> 200 idempotent
    if rec.get("payment_status") == "PAID":
        if rec.get("payment_external_id") == external_id:
            return {"accepted": True, "idempotent": True, "fee_record_id": fee_id}
        raise APIError("ERR_DUPLICATE_PAYMENT_EVENT",
                       "A different payment_external_id is already recorded for this fee record", 409)
    if rec.get("payment_status") != "UNPAID":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Fee record cannot be paid in {rec.get('payment_status')} state", 409)
    if (rec.get("amount_cents") or 0) <= 0:
        raise APIError("ERR_FEE_ZERO_NOT_PAYABLE",
                       "Cannot pay a zero-amount fee record", 409)
    rec["payment_status"] = "PAID"
    rec["payment_external_id"] = external_id
    stamp_update(rec)
    append_audit(actor_role, actor_id, "FEE_ADJUSTMENT", "OvertimeFeeRecord", fee_id,
                 {"event": "payment_succeeded", "external_id": external_id})
    return {"accepted": True, "idempotent": False, "fee_record_id": fee_id}


def _handle_payment_refunded(body: dict, actor_role: str, actor_id: str):
    fee_id = body.get("fee_record_id")
    external_id = body.get("payment_external_id")
    rec = None
    if fee_id:
        rec = DB.fee_records.get(fee_id)
    elif external_id:
        for r in DB.fee_records.values():
            if r.get("payment_external_id") == external_id:
                rec = r
                break
    if not rec:
        raise not_found("OvertimeFeeRecord not found for refund")
    if rec.get("payment_status") == "REFUNDED":
        return {"accepted": True, "idempotent": True, "fee_record_id": rec["id"]}
    if rec.get("payment_status") != "PAID":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Fee record must be PAID before refund (currently {rec.get('payment_status')})",
                       409)
    rec["payment_status"] = "REFUNDED"
    stamp_update(rec)
    append_audit(actor_role, actor_id, "FEE_ADJUSTMENT", "OvertimeFeeRecord", rec["id"],
                 {"event": "payment_refunded"})
    return {"accepted": True, "idempotent": False, "fee_record_id": rec["id"]}
