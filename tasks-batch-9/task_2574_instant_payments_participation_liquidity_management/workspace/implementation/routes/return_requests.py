"""Return requests and the compensating inbound credit."""

from flask import Blueprint

from db import bump, db, new_record, now, order_key
from errors import ApiError
from middleware import authorize, require_scope, scope_filter_value
from response import created, list_response, object_response
from routes.helpers import query_value
from timeutils import date_str, plus_minutes
from validation import opt_int, opt_string, payload, req_enum, req_id
from services import liquidity, lookup, serializers
from services.constants import (
    RETURN_DECLINE_REASON_CODES,
    RETURN_REASON_CODES,
    RETURN_REQUEST_WINDOW_MINUTES,
    RETURN_RESPONSE_SLA_MINUTES,
)

bp = Blueprint("return_requests", __name__)


@bp.route("/return-requests", methods=["POST"])
def lodge_return():
    authorize(["PaymentOperator"])
    body = payload()

    raw_participant = body.get("requested_by_participant_id")
    participant = None
    if isinstance(raw_participant, str) and raw_participant.strip():
        participant = lookup.participant(raw_participant)
    raw_transfer = body.get("credit_transfer_id")
    transfer = None
    if isinstance(raw_transfer, str) and raw_transfer.strip():
        transfer = lookup.credit_transfer(raw_transfer)

    transfer_id = req_id(body, "credit_transfer_id")
    participant_id = req_id(body, "requested_by_participant_id")
    reason_code = req_enum(body, "reason_code", RETURN_REASON_CODES)
    returned_amount = opt_int(body, "returned_amount_cents")
    narrative = opt_string(body, "narrative")
    assert transfer_id and participant_id

    if participant["enrollment_status"] != "LIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_LIVE", "The lodging bank is not LIVE.")
    if transfer["clearing_status"] != "SETTLED":
        raise ApiError("ERR_TRANSFER_NOT_SETTLED", "Only a settled transfer may be returned.")

    if participant["routing_number"] != transfer["receiver_routing_number"]:
        raise ApiError(
            "ERR_RETURN_REQUESTOR_NOT_RECEIVER",
            "Only the receiving side may lodge a return request.",
        )
    original_amount = transfer["amount_cents"]
    if returned_amount is None:
        returned_amount = original_amount
    elif returned_amount <= 0 or returned_amount > original_amount:
        raise ApiError(
            "ERR_RETURN_AMOUNT_INVALID",
            "returned_amount_cents must be positive and no greater than the original amount.",
        )

    if now() >= plus_minutes(transfer["settled_at"], RETURN_REQUEST_WINDOW_MINUTES):
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED", "The return request window has elapsed.")

    if transfer["exception_status"] != "NONE":
        raise ApiError(
            "ERR_DUPLICATE_RETURN_REQUEST",
            "The exception dimension of this transfer has already been used.",
        )

    request = new_record()
    request.update({
        "credit_transfer_id": transfer_id,
        "requested_by_participant_id": participant_id,
        "honored_transfer_id": None,
        "reason_code": reason_code,
        "original_amount_cents": original_amount,
        "returned_amount_cents": returned_amount,
        "status": "REQUESTED",
        "response_deadline_at": plus_minutes(now(), RETURN_RESPONSE_SLA_MINUTES),
        "narrative": narrative,
        "decline_reason_code": None,
    })
    db.return_requests[request["id"]] = request
    transfer["exception_status"] = "RETURN_REQUESTED"
    bump(transfer)
    return created(serializers.return_request(request))


@bp.route("/return-requests/<request_id>", methods=["GET"])
def get_return(request_id):
    user_id, role = authorize(["NetworkOperator", "PaymentOperator", "ParticipantAdmin"])
    request = lookup.return_request(request_id)
    if role == "ParticipantAdmin":
        transfer = lookup.credit_transfer(request["credit_transfer_id"])
        if user_id not in (request["requested_by_participant_id"],
                           transfer["originator_participant_id"]):
            require_scope(user_id, role, request["requested_by_participant_id"])
    return object_response(serializers.return_request(request))


@bp.route("/return-requests", methods=["GET"])
def list_returns():
    user_id, role = authorize(
        ["NetworkOperator", "PaymentOperator", "ParticipantAdmin", "CoreBankingSystem"]
    )
    requested_by = query_value("requested_by_participant_id")
    transfer_id = query_value("credit_transfer_id")
    honored_id = query_value("honored_transfer_id")
    status = query_value("status")
    if role == "ParticipantAdmin" and requested_by is not None:
        requested_by = scope_filter_value(user_id, role, requested_by)
    rows = []
    for row in db.return_requests.values():
        if requested_by is not None and row["requested_by_participant_id"] != requested_by:
            continue
        if transfer_id is not None and row["credit_transfer_id"] != transfer_id:
            continue
        if honored_id is not None and row["honored_transfer_id"] != honored_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if role == "ParticipantAdmin" and requested_by is None:
            transfer = db.credit_transfers.get(row["credit_transfer_id"])
            owner = transfer["originator_participant_id"] if transfer is not None else None
            if user_id not in (row["requested_by_participant_id"], owner):
                continue
        rows.append(row)
    rows.sort(key=order_key)
    return list_response(rows, serializers.return_request)


@bp.route("/return-requests/<request_id>/honor", methods=["POST"])
def honor_return(request_id):
    authorize(["NetworkOperator"])
    request = lookup.return_request(request_id)
    transfer = lookup.credit_transfer(request["credit_transfer_id"])
    if request["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a REQUESTED return may be honoured.")
    amount = request["returned_amount_cents"]
    if amount is None or amount <= 0 or amount > request["original_amount_cents"]:
        raise ApiError("ERR_RETURN_AMOUNT_INVALID", "The stored returned amount is not payable.")
    instant = now()
    if instant >= request["response_deadline_at"]:
        raise ApiError(
            "ERR_RETURN_RESPONSE_DEADLINE_PASSED",
            "The return response deadline has passed.",
        )

    # First hop.
    request["status"] = "HONORED"
    transfer["exception_status"] = "RETURN_HONORED"
    bump(transfer)

    # Second hop: mint the compensating inbound credit.
    compensating = new_record()
    compensating.update({
        "originator_participant_id": transfer["originator_participant_id"],
        "customer_account_id": transfer["customer_account_id"],
        "segment_policy_id": transfer["segment_policy_id"],
        "rfp_id": None,
        "compensating_for_transfer_id": transfer["id"],
        "receiver_routing_number": transfer["receiver_routing_number"],
        "amount_cents": amount,
        "direction": "INBOUND",
        "rail": "INSTANT",
        "clearing_status": "SETTLED",
        "exception_status": "NONE",
        "fraud_score": 0,
        "fraud_reason_codes": [],
        "initiated_by_user_id": None,
        "settlement_business_date": date_str(instant),
        "accepted_at": None,
        "irrevocable_at": None,
        "settled_at": instant,
        "queued_at": None,
        "remittance_reference": None,
        "rejection_reason_code": None,
    })
    db.credit_transfers[compensating["id"]] = compensating
    request["honored_transfer_id"] = compensating["id"]
    bump(request)

    # Third and fourth hops: the credit, the re-band and the alert clearance.
    participant = lookup.participant(transfer["originator_participant_id"])
    account = lookup.account_of_participant(participant["id"])
    if account is not None:
        liquidity.post_ledger_entry(
            account, "RETURN_CREDIT", amount, related_transfer_id=transfer["id"],
        )
        # Fifth hop: the posture lift and the queue release pass.
        liquidity.rederive_posture(participant)
    return object_response(serializers.return_request(request))


@bp.route("/return-requests/<request_id>/decline", methods=["POST"])
def decline_return(request_id):
    authorize(["NetworkOperator"])
    request = lookup.return_request(request_id)
    transfer = lookup.credit_transfer(request["credit_transfer_id"])
    body = payload()
    reason_code = req_enum(body, "decline_reason_code", RETURN_DECLINE_REASON_CODES)
    if request["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a REQUESTED return may be declined.")
    if now() >= request["response_deadline_at"]:
        raise ApiError(
            "ERR_RETURN_RESPONSE_DEADLINE_PASSED",
            "The return response deadline has passed.",
        )
    request["status"] = "DECLINED"
    request["decline_reason_code"] = reason_code
    bump(request)
    transfer["exception_status"] = "RETURN_DECLINED"
    bump(transfer)
    return object_response(serializers.return_request(request))
