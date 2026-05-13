"""System routes: clock advance and external-event emit."""
from flask import Blueprint

from clock import format_iso, get_now, parse_iso, set_now
from common import get_json_body, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import emit_audit
from services.cascades import run_clock_cascades


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_roles({"PlatformOps"})
    body = get_json_body()
    to_s = body.get("to")
    to_dt = parse_iso(to_s)
    if not to_dt:
        raise api_error("ERR_VALIDATION", "to must be a valid ISO 8601 timestamp")
    set_now(to_dt)
    run_clock_cascades()
    return success({"now": format_iso(get_now())})


@bp.route("/_events/emit", methods=["POST"])
def events_emit():
    user_id, _ = require_roles({"PlatformOps"})
    body = get_json_body()
    event_type = body.get("event_type")
    subject_id = body.get("subject_id")
    payload = body.get("payload") or {}

    if event_type == "PAYMENT_COMPLETED":
        payment = db.prize_payments.get(subject_id)
        if not payment:
            raise api_error("ERR_FK_NOT_FOUND", "prize payment not found")
        if payment.get("status") != "PAYING":
            raise api_error("ERR_INVALID_STATE", "payment must be PAYING")
        payment["status"] = "PAID"
        payment["external_payment_ref"] = payload.get("external_payment_ref") or payload.get("ref")
        stamp_update(payment)
        emit_audit(
            "PRIZE_PAID",
            "SYSTEM",
            user_id,
            "PRIZE_PAYMENT",
            payment["id"],
            {"external_payment_ref": payment["external_payment_ref"]},
        )
        return success({"prize_payment_id": payment["id"], "status": "PAID"})

    if event_type == "PAYMENT_FAILED":
        payment = db.prize_payments.get(subject_id)
        if not payment:
            raise api_error("ERR_FK_NOT_FOUND", "prize payment not found")
        if payment.get("status") != "PAYING":
            raise api_error("ERR_INVALID_STATE", "payment must be PAYING")
        payment["status"] = "FAILED"
        stamp_update(payment)
        return success({"prize_payment_id": payment["id"], "status": "FAILED"})

    if event_type == "COPYRIGHT_REGISTERED":
        transfer = db.copyright_transfers.get(subject_id)
        if not transfer:
            raise api_error("ERR_FK_NOT_FOUND", "copyright transfer not found")
        if transfer.get("status") != "REGISTERING":
            raise api_error("ERR_INVALID_STATE", "transfer must be REGISTERING")
        transfer["status"] = "REGISTERED"
        transfer["registration_ref"] = payload.get("registration_ref") or payload.get("ref")
        transfer["registered_at"] = format_iso(get_now())
        stamp_update(transfer)
        emit_audit(
            "COPYRIGHT_REGISTERED",
            "SYSTEM",
            user_id,
            "COPYRIGHT_TRANSFER",
            transfer["id"],
            {"registration_ref": transfer["registration_ref"]},
        )
        return success({"copyright_transfer_id": transfer["id"], "status": "REGISTERED"})

    raise api_error("ERR_VALIDATION", f"unknown event_type {event_type}")
