"""Payment notice endpoints — confirm / reverse."""

import hashlib
import json

from flask import Blueprint, g, request

from clock import now, parse_iso, to_iso
from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_IDEMPOTENCY_KEY_REQUIRED,
    ERR_IDEMPOTENCY_CONFLICT,
    ERR_PAYMENT_NOTICE_EXPIRED,
    ERR_VOUCHER_REQUIRED,
    ERR_REFUND_ALREADY_EXECUTED,
    forbidden,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.cascades import cascade_order_on_declaration_status
from services.common import check_occ, emit_audit, get_body, touch
from services.serializers import serialize_payment_notice


bp = Blueprint("payments", __name__)


def _can_view_notice(pn: dict) -> bool:
    role = g.role
    if role in ("FinanceOfficer", "Auditor", "CustomsOfficer"):
        return True
    dec = DB.declarations.get(pn["declaration_id"])
    if dec is None:
        return False
    if role == "Declarant":
        return dec["declarant_id"] == g.user_id
    if role == "Importer":
        order = DB.orders.get(dec["order_id"])
        return order is not None and order["importer_id"] == g.user_id
    return False


@bp.route("/payment_notices/<notice_id>", methods=["GET"])
@require_roles("Declarant", "FinanceOfficer", "Importer", "Auditor", "CustomsOfficer")
def get_notice(notice_id):
    pn = DB.payment_notices.get(notice_id)
    if pn is None:
        raise not_found("PaymentNotice not found")
    if not _can_view_notice(pn):
        raise forbidden("Cannot view this PaymentNotice")
    return success_object(serialize_payment_notice(pn), status=200)


def _payload_hash(payload: dict) -> str:
    serial = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serial.encode()).hexdigest()


@bp.route("/payment_notices/<notice_id>/confirm_payment", methods=["POST"])
@require_roles("FinanceOfficer")
def confirm_payment(notice_id):
    idempotency_header = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_header:
        raise APIError(ERR_IDEMPOTENCY_KEY_REQUIRED,
                       "Idempotency-Key header required", 400)

    body = get_body()
    payment_channel = body.get("payment_channel")
    voucher_url = body.get("voucher_url")
    idempotency_key_body = body.get("idempotency_key")

    if payment_channel not in ("BANK_TRANSFER", "ELECTRONIC_PAYMENT", "GUARANTEE_DEDUCTION"):
        raise APIError(ERR_INVALID_REQUEST, "Invalid payment_channel", 400)
    if not isinstance(idempotency_key_body, str) or idempotency_key_body.strip() == "":
        raise APIError(ERR_IDEMPOTENCY_KEY_REQUIRED,
                       "idempotency_key body field required", 400)

    with LOCK:
        pn = DB.payment_notices.get(notice_id)
        if pn is None:
            raise not_found("PaymentNotice not found")

        # Idempotency record check
        notice_idem = DB.idempotency.setdefault(notice_id, {})
        existing = notice_idem.get(idempotency_header)
        # Build canonical payload for hashing
        canonical = {
            "payment_channel": payment_channel,
            "voucher_url": voucher_url,
            "idempotency_key": idempotency_key_body,
        }
        new_hash = _payload_hash(canonical)
        if existing is not None:
            if existing["hash"] != new_hash:
                raise APIError(ERR_IDEMPOTENCY_CONFLICT,
                               "Same Idempotency-Key with different payload", 409)
            # Replay stored result.
            return success_object(existing["result"], status=200)

        # PRD §2.9 fixes priority: state-transition validity (ERR_INVALID_STATE_TRANSITION)
        # runs BEFORE business-temporal checks (payment notice expiry).
        # So: a notice that is PAID/REVERSED/EXPIRED should surface the
        # state-transition error, not the expiry error, even when the
        # notice is also past its due_at.
        if pn["status"] != "PENDING":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "PaymentNotice not in PENDING", 409)

        # Payment-notice expiry check (PRD §3.8) — notice expired iff now >= due_at
        due_at_dt = parse_iso(pn["due_at"])
        if now() >= due_at_dt:
            # Auto-expire (notice was PENDING up to here)
            pn["status"] = "EXPIRED"
            touch(pn)
            raise APIError(ERR_PAYMENT_NOTICE_EXPIRED, "Payment notice expired", 409)

        # Voucher required for BANK_TRANSFER
        if payment_channel == "BANK_TRANSFER":
            if not isinstance(voucher_url, str) or voucher_url.strip() == "":
                raise APIError(ERR_VOUCHER_REQUIRED, "voucher_url required for BANK_TRANSFER", 422)

        dec = DB.declarations.get(pn["declaration_id"])
        if dec is None:
            raise not_found("Declaration not found")

        # GUARANTEE_DEDUCTION requires linked declaration in APPROVED or CONDITIONALLY_RELEASED
        if payment_channel == "GUARANTEE_DEDUCTION":
            if dec["status"] not in ("APPROVED", "CONDITIONALLY_RELEASED"):
                raise APIError(ERR_INVALID_STATE_TRANSITION,
                               "GUARANTEE_DEDUCTION requires APPROVED or CONDITIONALLY_RELEASED", 409)

        # Pin payment channel
        pn["payment_channel"] = payment_channel
        pn["voucher_url"] = voucher_url
        pn["idempotency_key"] = idempotency_key_body
        pn["status"] = "PAID"
        touch(pn)

        # Cascade declaration APPROVED→RELEASED or CONDITIONALLY_RELEASED→RELEASED
        prior_dec_status = dec["status"]
        if dec["status"] in ("APPROVED", "CONDITIONALLY_RELEASED"):
            before = {"status": dec["status"]}
            dec["status"] = "RELEASED"
            dec["release_condition"] = None
            touch(dec)
            emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                       before_value=before, after_value={"status": "RELEASED"})
            order = DB.orders.get(dec["order_id"])
            if order is not None:
                cascade_order_on_declaration_status(order, dec, prior_dec_status, "RELEASED")

        emit_audit("PAYMENT_NOTICE", pn["id"], "PAYMENT_CONFIRMED",
                   before_value={"status": "PENDING"},
                   after_value={"status": "PAID", "payment_channel": payment_channel})
        emit_audit("PAYMENT_NOTICE", pn["id"], "EXTERNAL_SYNC",
                   before_value={},
                   after_value={"external_system": "PAYMENT_GATEWAY_PUSH"})

        result = serialize_payment_notice(pn)
        notice_idem[idempotency_header] = {"hash": new_hash, "result": result}
        return success_object(result, status=200)


@bp.route("/payment_notices/<notice_id>/reverse", methods=["POST"])
@require_roles("FinanceOfficer")
def reverse_payment(notice_id):
    body = get_body()
    reverse_reason = body.get("reverse_reason")
    if not isinstance(reverse_reason, str) or reverse_reason.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "reverse_reason required", 400)

    with LOCK:
        pn = DB.payment_notices.get(notice_id)
        if pn is None:
            raise not_found("PaymentNotice not found")
        if pn["status"] != "PAID":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Reverse only from PAID", 409)
        # No EXECUTED Refund for declaration
        for rf in DB.refunds.values():
            if rf["declaration_id"] == pn["declaration_id"] and rf["status"] == "EXECUTED":
                raise APIError(ERR_REFUND_ALREADY_EXECUTED,
                               "An EXECUTED refund exists; cannot reverse", 409)

        check_occ(pn, body)
        pn["status"] = "REVERSED"
        touch(pn)

        dec = DB.declarations.get(pn["declaration_id"])
        if dec is not None:
            if dec["status"] == "RELEASED":
                # Revert to APPROVED
                before = {"status": "RELEASED"}
                dec["status"] = "APPROVED"
                touch(dec)
                emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                           before_value=before, after_value={"status": "APPROVED"})
                # Revert order RELEASED→DECLARED
                order = DB.orders.get(dec["order_id"])
                if order is not None and order["status"] == "RELEASED":
                    order["status"] = "DECLARED"
                    touch(order)
        emit_audit("PAYMENT_NOTICE", pn["id"], "PAYMENT_CONFIRMED",
                   before_value={"status": "PAID"},
                   after_value={"status": "REVERSED", "reverse": True,
                                "reverse_reason": reverse_reason})
        return success_object(serialize_payment_notice(pn), status=200)
