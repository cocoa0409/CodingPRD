"""Requests for payment: raising, delivery, response and amendment."""

from flask import Blueprint

from db import bump, db, new_record, now, order_key
from errors import ApiError
from middleware import authorize, require_scope, scope_filter_value
from response import created, list_response, object_response
from routes.helpers import query_value
from timeutils import parse_instant, plus_minutes
from validation import opt_string, payload, req_amount, req_enum, req_id, req_string
from services import lookup, serializers
from services.constants import (
    MAX_AMENDMENT_ROUNDS,
    REQUESTING_MODELS,
    RFP_DECLINE_REASON_CODES,
    RFP_RESPONSES,
    RFP_RESPONSE_SLA_MINUTES,
)

bp = Blueprint("request_for_payments", __name__)


def _deadline(expiry_at, delivered_at):
    sla = plus_minutes(delivered_at, RFP_RESPONSE_SLA_MINUTES)
    return sla if sla < expiry_at else expiry_at


@bp.route("/request-for-payments", methods=["POST"])
def raise_request():
    authorize(["PaymentOperator"])
    body = payload()

    raw_requestor = body.get("requestor_participant_id")
    participant = None
    if isinstance(raw_requestor, str) and raw_requestor.strip():
        participant = lookup.participant(raw_requestor)
    raw_debtor = body.get("debtor_customer_account_id")
    debtor = None
    if isinstance(raw_debtor, str) and raw_debtor.strip():
        debtor = lookup.customer_account(raw_debtor)

    requestor_id = req_id(body, "requestor_participant_id")
    debtor_id = req_id(body, "debtor_customer_account_id")
    amount = req_amount(body, "amount_cents")
    expiry_at = parse_instant(req_string(body, "expiry_at"))
    memo = opt_string(body, "memo")
    assert requestor_id and debtor_id

    if expiry_at <= now():
        raise ApiError("ERR_INVALID_INTERVAL", "expiry_at must be later than the current clock.")

    if participant["enrollment_status"] != "LIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_LIVE", "The requesting bank is not LIVE.")
    if participant["operational_posture"] == "OFFLINE":
        raise ApiError("ERR_PARTICIPANT_OFFLINE", "The requesting bank is OFFLINE.")

    debtor_bank = lookup.participant(debtor["participant_id"])
    if participant["participation_model"] not in REQUESTING_MODELS:
        raise ApiError(
            "ERR_REQUEST_NOT_PERMITTED_FOR_MODEL",
            "The requesting bank's participation model has no request capability.",
        )
    if debtor_bank["participation_model"] not in REQUESTING_MODELS:
        raise ApiError(
            "ERR_REQUEST_NOT_PERMITTED_FOR_MODEL",
            "The debtor's bank cannot receive requests for payment.",
        )
    if debtor["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_RESTRICTED", "The debtor customer account is restricted.")

    rfp = new_record()
    rfp.update({
        "requestor_participant_id": requestor_id,
        "debtor_customer_account_id": debtor_id,
        "amount_cents": amount,
        "expiry_at": expiry_at,
        "memo": memo,
        "status": "CREATED",
        "delivered_at": None,
        "response_deadline_at": None,
        "amendment_round": 0,
        "last_response": None,
        "decline_reason_code": None,
    })
    db.request_for_payments[rfp["id"]] = rfp
    return created(serializers.request_for_payment(rfp))


@bp.route("/request-for-payments/<rfp_id>", methods=["GET"])
def get_request(rfp_id):
    user_id, role = authorize(["NetworkOperator", "PaymentOperator", "ParticipantAdmin"])
    rfp = lookup.request_for_payment(rfp_id)
    if role == "ParticipantAdmin":
        debtor = lookup.customer_account(rfp["debtor_customer_account_id"])
        if user_id not in (rfp["requestor_participant_id"], debtor["participant_id"]):
            require_scope(user_id, role, rfp["requestor_participant_id"])
    return object_response(serializers.request_for_payment(rfp))


@bp.route("/request-for-payments", methods=["GET"])
def list_requests():
    user_id, role = authorize(
        ["NetworkOperator", "PaymentOperator", "ParticipantAdmin", "LiquidityOfficer"]
    )
    requestor = query_value("requestor_participant_id")
    debtor_account = query_value("debtor_customer_account_id")
    status = query_value("status")
    if role == "ParticipantAdmin" and requestor is not None:
        requestor = scope_filter_value(user_id, role, requestor)
    rows = []
    for row in db.request_for_payments.values():
        if requestor is not None and row["requestor_participant_id"] != requestor:
            continue
        if debtor_account is not None and row["debtor_customer_account_id"] != debtor_account:
            continue
        if status is not None and row["status"] != status:
            continue
        if role == "ParticipantAdmin" and requestor is None:
            debtor = db.customer_accounts.get(row["debtor_customer_account_id"])
            owner = debtor["participant_id"] if debtor is not None else None
            if user_id not in (row["requestor_participant_id"], owner):
                continue
        rows.append(row)
    rows.sort(key=order_key)
    return list_response(rows, serializers.request_for_payment)


@bp.route("/request-for-payments/<rfp_id>/delivery", methods=["POST"])
def deliver_request(rfp_id):
    authorize(["NetworkOperator"])
    rfp = lookup.request_for_payment(rfp_id)
    participant = lookup.participant(rfp["requestor_participant_id"])
    if participant["enrollment_status"] != "LIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_LIVE", "The requesting bank is not LIVE.")
    if rfp["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a CREATED request may be delivered.")
    if now() >= rfp["expiry_at"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The request has reached its expiry.")
    if participant["participation_model"] not in REQUESTING_MODELS:
        raise ApiError(
            "ERR_REQUEST_NOT_PERMITTED_FOR_MODEL",
            "The requesting bank's participation model has no request capability.",
        )
    instant = now()
    rfp["status"] = "DELIVERED"
    rfp["delivered_at"] = instant
    rfp["response_deadline_at"] = _deadline(rfp["expiry_at"], instant)
    bump(rfp)
    return object_response(serializers.request_for_payment(rfp))


@bp.route("/request-for-payments/<rfp_id>/response", methods=["POST"])
def respond_to_request(rfp_id):
    authorize(["PaymentOperator"])
    rfp = lookup.request_for_payment(rfp_id)
    body = payload()
    response = req_enum(body, "response", RFP_RESPONSES)
    reason_code = None
    if response == "DECLINE":
        reason_code = req_enum(body, "decline_reason_code", RFP_DECLINE_REASON_CODES)

    if rfp["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DELIVERED request may be answered.")

    debtor = lookup.customer_account(rfp["debtor_customer_account_id"])
    if response == "ACCEPT" and debtor["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_RESTRICTED", "The debtor customer account is restricted.")

    instant = now()
    if instant >= rfp["expiry_at"]:
        raise ApiError("ERR_RFP_EXPIRED", "The request for payment has expired.")
    if rfp["response_deadline_at"] is not None and instant >= rfp["response_deadline_at"]:
        raise ApiError("ERR_RFP_EXPIRED", "The message response deadline has passed.")

    if response == "REQUEST_AMENDMENT" and rfp["amendment_round"] >= MAX_AMENDMENT_ROUNDS:
        raise ApiError(
            "ERR_AMENDMENT_ROUNDS_EXHAUSTED",
            "No further amendment round is permitted for this request.",
        )

    rfp["last_response"] = response
    if response == "ACCEPT":
        rfp["status"] = "ACCEPTED"
    elif response == "DECLINE":
        rfp["status"] = "DECLINED"
        rfp["decline_reason_code"] = reason_code
    else:
        rfp["status"] = "AMENDMENT_REQUESTED"
        rfp["response_deadline_at"] = None
    bump(rfp)
    return object_response(serializers.request_for_payment(rfp))


@bp.route("/request-for-payments/<rfp_id>/amendment", methods=["POST"])
def amend_request(rfp_id):
    authorize(["PaymentOperator"])
    rfp = lookup.request_for_payment(rfp_id)
    body = payload()
    amount = req_amount(body, "amount_cents")
    memo = opt_string(body, "memo", default=rfp["memo"])

    if rfp["status"] != "AMENDMENT_REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a request awaiting amendment may be amended.",
        )
    instant = now()
    if instant >= rfp["expiry_at"]:
        raise ApiError("ERR_RFP_EXPIRED", "The request for payment has expired.")
    if rfp["amendment_round"] >= MAX_AMENDMENT_ROUNDS:
        raise ApiError(
            "ERR_AMENDMENT_ROUNDS_EXHAUSTED",
            "No further amendment round is permitted for this request.",
        )

    rfp["amount_cents"] = amount
    rfp["memo"] = memo
    rfp["amendment_round"] = rfp["amendment_round"] + 1
    rfp["last_response"] = None
    rfp["status"] = "DELIVERED"
    rfp["delivered_at"] = instant
    rfp["response_deadline_at"] = _deadline(rfp["expiry_at"], instant)
    bump(rfp)
    return object_response(serializers.request_for_payment(rfp))
