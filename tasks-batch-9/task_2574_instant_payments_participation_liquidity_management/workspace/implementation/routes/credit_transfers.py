"""Credit transfer origination, clearing, settlement and diversion."""

from flask import Blueprint

from db import bump, db, new_record, now, order_key
from errors import ApiError
from middleware import authorize, require_scope, scope_filter_value
from response import created, list_response, object_response
from routes.helpers import query_value
from timeutils import date_str
from validation import (
    opt_id,
    opt_string,
    payload,
    req_amount,
    req_enum,
    req_id,
    req_int,
    routing_number,
)
from services import fraud, limits, liquidity, lookup, serializers
from services.constants import (
    FRAUD_BLOCK_THRESHOLD,
    FRAUD_HOLD_THRESHOLD,
    OUTAGE_FALLBACK_RAILS,
    SENDING_MODELS,
    THROTTLED_PER_TXN_CAP_CENTS,
    VELOCITY_WINDOW_MINUTES,
)

bp = Blueprint("credit_transfers", __name__)

READ_ROLES = ["NetworkOperator", "PaymentOperator", "ParticipantAdmin", "FraudReviewer", "CoreBankingSystem"]


@bp.route("/credit-transfers", methods=["POST"])
def originate_transfer():
    user_id, _role = authorize(["PaymentOperator"])
    body = payload()

    # Rung 4 - body reference existence, in the pinned reference order.
    raw_originator = opt_id(body, "originator_participant_id")
    participant = lookup.participant(raw_originator) if raw_originator is not None else None
    raw_customer = opt_id(body, "customer_account_id")
    customer = lookup.customer_account(raw_customer) if raw_customer is not None else None
    raw_rfp = opt_id(body, "rfp_id")
    rfp = lookup.request_for_payment(raw_rfp) if raw_rfp is not None else None

    # Rung 5 - payload shape.
    originator_id = req_id(body, "originator_participant_id")
    customer_id = req_id(body, "customer_account_id")
    receiver = routing_number(body, "receiver_routing_number")
    amount = req_amount(body, "amount_cents")
    expected_version = req_int(body, "expected_position_account_version")
    remittance = opt_string(body, "remittance_reference")
    assert originator_id and customer_id

    account = lookup.account_of_participant(originator_id)

    # Rung 6 - stale-view protection.
    if account is not None and expected_version != account["version"]:
        raise ApiError(
            "ERR_STALE_POSITION_VERSION",
            "The position account version has advanced since it was read.",
        )

    # Rung 7 - lifecycle and posture state.
    if participant["enrollment_status"] != "LIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_LIVE", "The originating bank is not LIVE.")
    if participant["operational_posture"] == "OFFLINE":
        raise ApiError("ERR_PARTICIPANT_OFFLINE", "The originating bank is OFFLINE.")
    if participant["operational_posture"] == "SEND_FROZEN":
        raise ApiError("ERR_PARTICIPANT_SEND_FROZEN", "The originating bank is send-frozen.")

    # Rung 8 - network compliance.
    if participant["participation_model"] not in SENDING_MODELS:
        raise ApiError(
            "ERR_SEND_NOT_PERMITTED_FOR_MODEL",
            "The participation model does not permit originating payments.",
        )
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_RESTRICTED", "The debtor customer account is restricted.")

    # Rung 9 - referential coherence.
    if customer["participant_id"] != originator_id:
        raise ApiError(
            "ERR_CUSTOMER_ACCOUNT_PARTICIPANT_MISMATCH",
            "That customer account belongs to a different participant.",
        )
    policy = limits.governing_policy(originator_id, customer["segment"])
    if policy is None:
        raise ApiError(
            "ERR_NO_GOVERNING_SEGMENT_POLICY",
            "No segment policy governs this participant and segment at the current clock.",
        )
    if rfp is not None:
        if (rfp["status"] != "ACCEPTED"
                or rfp["debtor_customer_account_id"] != customer_id
                or rfp["amount_cents"] != amount):
            raise ApiError(
                "ERR_RFP_FULFILMENT_MISMATCH",
                "The fulfilment does not match the accepted request for payment.",
            )

    # Rung 10 - temporal.
    if rfp is not None and now() >= rfp["expiry_at"]:
        raise ApiError("ERR_RFP_EXPIRED", "The request for payment has expired.")

    # Rung 11 - limits, in the pinned internal order.
    if amount > policy["per_transaction_limit_cents"]:
        raise ApiError(
            "ERR_PER_TRANSACTION_LIMIT_EXCEEDED",
            "The amount exceeds the governing per-transaction limit.",
        )
    if participant["operational_posture"] == "THROTTLED" and amount > THROTTLED_PER_TXN_CAP_CENTS:
        raise ApiError(
            "ERR_THROTTLED_CAP_EXCEEDED",
            "A throttled participant may not send more than %d cents per transfer."
            % THROTTLED_PER_TXN_CAP_CENTS,
        )
    window_rows = limits.velocity_rows(customer_id, VELOCITY_WINDOW_MINUTES)
    window_count = len(window_rows)
    if window_count + 1 > policy["rolling_window_count_limit"]:
        raise ApiError("ERR_VELOCITY_LIMIT_EXCEEDED", "The rolling window count limit is exceeded.")
    window_amount = sum(row["amount_cents"] for row in window_rows)
    if window_amount + amount > policy["rolling_window_amount_limit_cents"]:
        raise ApiError("ERR_VELOCITY_LIMIT_EXCEEDED", "The rolling window amount limit is exceeded.")
    if limits.daily_exposure(customer_id) + amount > policy["daily_aggregate_limit_cents"]:
        raise ApiError("ERR_DAILY_LIMIT_EXCEEDED", "The daily aggregate limit is exceeded.")

    # Rung 12 - liquidity.
    if liquidity.available(account) - amount < account["floor_cents"]:
        raise ApiError(
            "ERR_INSUFFICIENT_LIQUIDITY",
            "The send would take available liquidity below the regulatory floor.",
        )

    transfer = new_record()
    transfer.update({
        "originator_participant_id": originator_id,
        "customer_account_id": customer_id,
        "segment_policy_id": policy["id"],
        "rfp_id": rfp["id"] if rfp is not None else None,
        "compensating_for_transfer_id": None,
        "receiver_routing_number": receiver,
        "amount_cents": amount,
        "direction": "OUTBOUND",
        "rail": "INSTANT",
        "clearing_status": "INITIATED",
        "exception_status": "NONE",
        "fraud_score": 0,
        "fraud_reason_codes": [],
        "initiated_by_user_id": user_id,
        "settlement_business_date": None,
        "accepted_at": None,
        "irrevocable_at": None,
        "settled_at": None,
        "queued_at": None,
        "remittance_reference": remittance,
        "rejection_reason_code": None,
    })
    db.credit_transfers[transfer["id"]] = transfer
    bump(account)

    score, reason_codes = fraud.score_at_origination(customer, amount, receiver, window_count)
    transfer["fraud_score"] = score
    transfer["fraud_reason_codes"] = reason_codes

    if score >= FRAUD_BLOCK_THRESHOLD:
        transfer["clearing_status"] = "REJECTED"
        transfer["rejection_reason_code"] = "FRAUD_BLOCK_AUTOMATIC"
    elif score >= FRAUD_HOLD_THRESHOLD:
        transfer["clearing_status"] = "FRAUD_HOLD"
        review = new_record()
        review.update({
            "credit_transfer_id": transfer["id"],
            "score_at_origination": score,
            "final_fraud_score": None,
            "queue_priority": 1 if score >= 75 else 2,
            "status": "QUEUED",
            "assigned_reviewer_user_id": None,
            "sla_deadline_at": None,
            "decision_rationale": None,
        })
        db.fraud_reviews[review["id"]] = review
    return created(serializers.credit_transfer(transfer))


@bp.route("/credit-transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    user_id, role = authorize(READ_ROLES)
    transfer = lookup.credit_transfer(transfer_id)
    require_scope(user_id, role, transfer["originator_participant_id"])
    return object_response(serializers.credit_transfer(transfer))


@bp.route("/credit-transfers", methods=["GET"])
def list_transfers():
    user_id, role = authorize(READ_ROLES)
    originator = scope_filter_value(user_id, role, query_value("originator_participant_id"))
    filters = {
        "originator_participant_id": originator,
        "customer_account_id": query_value("customer_account_id"),
        "segment_policy_id": query_value("segment_policy_id"),
        "rfp_id": query_value("rfp_id"),
        "compensating_for_transfer_id": query_value("compensating_for_transfer_id"),
        "clearing_status": query_value("clearing_status"),
        "exception_status": query_value("exception_status"),
        "settlement_business_date": query_value("settlement_business_date"),
    }
    rows = []
    for row in db.credit_transfers.values():
        keep = True
        for field, wanted in filters.items():
            if wanted is not None and row[field] != wanted:
                keep = False
                break
        if keep:
            rows.append(row)
    rows.sort(key=order_key)
    return list_response(rows, serializers.credit_transfer)


@bp.route("/credit-transfers/<transfer_id>/acceptance", methods=["POST"])
def accept_transfer(transfer_id):
    authorize(["NetworkOperator"])
    transfer = lookup.credit_transfer(transfer_id)
    if transfer["clearing_status"] == "SETTLED":
        raise ApiError("ERR_TRANSFER_IRREVOCABLE", "A settled transfer is irrevocable.")
    if transfer["clearing_status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Acceptance is only declared from INITIATED.")
    participant = lookup.participant(transfer["originator_participant_id"])
    customer = lookup.customer_account(transfer["customer_account_id"])
    if participant["enrollment_status"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The originating bank is not LIVE.")
    if participant["operational_posture"] not in ("NORMAL", "THROTTLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The originating bank may not clear sends now.")
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The debtor customer account is restricted.")
    instant = now()
    transfer["clearing_status"] = "ACCEPTED"
    transfer["accepted_at"] = instant
    transfer["irrevocable_at"] = instant
    bump(transfer)
    return object_response(serializers.credit_transfer(transfer))


@bp.route("/credit-transfers/<transfer_id>/settlement", methods=["POST"])
def settle_transfer(transfer_id):
    authorize(["NetworkOperator"])
    transfer = lookup.credit_transfer(transfer_id)
    if transfer["clearing_status"] == "SETTLED":
        raise ApiError("ERR_TRANSFER_IRREVOCABLE", "A settled transfer is irrevocable.")
    if transfer["clearing_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Settlement is only declared from ACCEPTED.")
    cycle = lookup.cycle_for_business_date(date_str(now()))
    if cycle is None or cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", "No settlement cycle is OPEN for today.")
    participant = lookup.participant(transfer["originator_participant_id"])
    account = lookup.account_of_participant_or_fail(participant["id"])

    transfer["clearing_status"] = "SETTLED"
    transfer["settled_at"] = now()
    transfer["settlement_business_date"] = cycle["business_date"]
    bump(transfer)
    liquidity.post_ledger_entry(
        account, "TRANSFER_DEBIT", transfer["amount_cents"], related_transfer_id=transfer["id"],
    )
    liquidity.rederive_posture(participant)
    return object_response(serializers.credit_transfer(transfer))


@bp.route("/credit-transfers/<transfer_id>/diversion", methods=["POST"])
def divert_transfer(transfer_id):
    authorize(["NetworkOperator", "PaymentOperator"])
    transfer = lookup.credit_transfer(transfer_id)
    body = payload()
    rail = req_enum(body, "fallback_rail", OUTAGE_FALLBACK_RAILS)
    if transfer["clearing_status"] == "SETTLED":
        raise ApiError("ERR_TRANSFER_IRREVOCABLE", "A settled transfer is irrevocable.")
    if transfer["clearing_status"] != "QUEUED_THROTTLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a queued transfer may be diverted.")
    if transfer["irrevocable_at"] is not None:
        raise ApiError("ERR_TRANSFER_IRREVOCABLE", "An irrevocable transfer may not be diverted.")
    event = None
    for candidate in liquidity.covering_outages(transfer["originator_participant_id"]):
        if candidate["fallback_rail"] == rail and rail != "NONE":
            event = candidate
            break
    if event is None:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "No declared outage covering this participant offers that fallback rail.",
        )
    transfer["rail"] = rail
    transfer["clearing_status"] = "DIVERTED"
    bump(transfer)
    event["diverted_transfer_count"] = event["diverted_transfer_count"] + 1
    bump(event)
    return object_response(serializers.credit_transfer(transfer))


@bp.route("/credit-transfers/<transfer_id>/ledger-entries", methods=["GET"])
def list_transfer_ledger_entries(transfer_id):
    authorize(["NetworkOperator", "LiquidityOfficer", "PaymentOperator", "CoreBankingSystem"])
    lookup.credit_transfer(transfer_id)
    rows = [e for e in db.ledger_entries.values() if e["related_transfer_id"] == transfer_id]
    entry_type = query_value("entry_type")
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    rows.sort(key=lambda e: e["sequence_no"])
    return list_response(rows, serializers.ledger_entry)


@bp.route("/credit-transfers/<transfer_id>/fraud-reviews", methods=["GET"])
def list_transfer_fraud_reviews(transfer_id):
    authorize(["NetworkOperator", "FraudReviewer", "PaymentOperator"])
    lookup.credit_transfer(transfer_id)
    rows = lookup.reviews_of_transfer(transfer_id)
    status = query_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.reverse()
    return list_response(rows, serializers.fraud_review)
