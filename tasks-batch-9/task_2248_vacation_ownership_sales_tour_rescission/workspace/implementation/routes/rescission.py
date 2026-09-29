"""Cancellation intake, adjudication and refund settlement (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import collect, get_agreement, get_refund, get_rescission, page
from store import db, ordered

bp = Blueprint("rescission", __name__)

DELIVERY_METHODS = ("HAND_DELIVERED", "CERTIFIED_MAIL", "EMAIL")
REQUEST_STATUSES = ("RECEIVED", "VALIDATED", "REJECTED_LATE", "REFUNDED")
REFUND_METHODS = ("ACH", "CHECK", "CARD_REVERSAL")
REFUND_STATUSES = ("PENDING", "ISSUED")


@bp.post("/rescission-requests")
def create_request():
    user_id, _ = auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    agreement_id = validators.identifier(data, "agreement_id")
    delivery_method = validators.enum(data, "delivery_method", DELIVERY_METHODS)
    postmark = validators.datetime_field(data, "postmark_utc", required=False)

    agreement = get_agreement(agreement_id)
    if agreement["fulfillment_status"] != "AWAITING_FUNDING":
        fail(errors.ERR_AGREEMENT_ALREADY_FUNDED, "the contract has moved past funding")

    now = db.now()
    if delivery_method == "CERTIFIED_MAIL" and postmark is not None:
        basis = "POSTMARK"
        effective = postmark
    else:
        basis = "RECEIPT"
        effective = now

    request_record = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "agreement_id": agreement["id"],
        "delivery_method": delivery_method,
        "postmark_utc": postmark,
        "received_at": now,
        "intake_user_id": user_id,
        "timeliness_basis": basis,
        "effective_utc": effective,
        "is_timely": effective <= agreement["rescission_deadline_utc"],
        "status": "RECEIVED",
        "adjudicated_at": None,
        "adjudicated_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rescissions[request_record["id"]] = request_record
    return created(request_record)


@bp.post("/rescission-requests/<request_id>/adjudicate")
def adjudicate(request_id):
    user_id, _ = auth.require(auth.CONTRACT_ADMINISTRATOR)
    request_record = get_rescission(request_id)
    if request_record["status"] != "RECEIVED":
        fail(errors.ERR_INVALID_RESCISSION_REQUEST_STATE, "request is not RECEIVED")
    agreement = db.agreements.get(request_record["agreement_id"])
    if agreement["fulfillment_status"] != "AWAITING_FUNDING":
        fail(errors.ERR_AGREEMENT_ALREADY_FUNDED, "the contract has moved past funding")

    now = db.now()
    derive.setf(request_record, "adjudicated_at", now)
    derive.setf(request_record, "adjudicated_by_user_id", user_id)

    if not request_record["is_timely"]:
        # Divergent branch: the agreement is not touched at all.
        derive.setf(request_record, "status", "REJECTED_LATE")
        return ok(request_record)

    derive.setf(request_record, "status", "VALIDATED")
    # CASCADE STEP 1
    derive.setf(agreement, "rescission_status", "RESCINDED")
    derive.setf(agreement, "fulfillment_status", "VOIDED")
    rep = db.reps.get(agreement["rep_id"])
    if rep is not None:
        # CASCADE STEP 2
        derive.recompute_rescinded_count(rep)
        analysis = derive.recompute_rep_cancellation(rep)
        # CASCADE STEP 3
        if analysis["retraining_required"]:
            derive.new_assignment(
                rep,
                "CANCELLATION_RATE_BREACH",
                calc.AUTO_RETRAINING_MODULE_COUNT,
                cancellation_rate=analysis["cancellation_rate"],
            )
            if rep["status"] == "ACTIVE":
                derive.setf(rep, "status", "RETRAINING")
            # CASCADE STEP 4
            derive.recompute_gallery_reps(db.galleries.get(rep["gallery_id"]))
    # FAN-OUT of step 1
    for application in ordered(db.financings.values()):
        if application["agreement_id"] != agreement["id"]:
            continue
        if application["status"] in ("SUBMITTED", "APPROVED"):
            derive.setf(application, "status", "CANCELLED")
    return ok(request_record)


@bp.get("/rescission-requests/<request_id>")
def read_request(request_id):
    auth.require_any()
    return ok(get_rescission(request_id))


@bp.get("/rescission-requests")
def list_requests():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.rescissions,
        (("agreement_id", "agreement_id"), ("status", "status", REQUEST_STATUSES)),
    )
    return listing(rows, limit, offset)


# ----------------------------------------------------------- disbursements
@bp.post("/refund-disbursements")
def create_disbursement():
    user_id, _ = auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    request_id = validators.identifier(data, "rescission_request_id")
    method = validators.enum(data, "method", REFUND_METHODS)

    request_record = get_rescission(request_id)
    if request_record["status"] != "VALIDATED":
        fail(errors.ERR_INVALID_RESCISSION_REQUEST_STATE, "request is not VALIDATED")
    for existing in db.refunds.values():
        if existing["rescission_request_id"] == request_record["id"]:
            fail(errors.ERR_REFUND_ALREADY_ISSUED, "a disbursement already exists")
    if request_record["adjudicated_by_user_id"] == user_id:
        fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "the adjudicating administrator may not issue the refund",
        )

    agreement = db.agreements.get(request_record["agreement_id"])
    money = calc.refund_settlement(
        agreement["refund_policy"],
        agreement["escrow_collected_cents"],
        _booking_gift_value(agreement),
    )

    now = db.now()
    disbursement = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "rescission_request_id": request_record["id"],
        "method": method,
        "refund_policy_applied": agreement["refund_policy"],
        "base_refund_cents": money["base_refund_cents"],
        "gift_recapture_cents": money["gift_recapture_cents"],
        "doc_fee_retained_cents": money["doc_fee_retained_cents"],
        "disbursed_amount_cents": money["disbursed_amount_cents"],
        "status": "PENDING",
        "issued_by_user_id": user_id,
        "settlement_reference": None,
        "settled_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.refunds[disbursement["id"]] = disbursement
    return created(disbursement)


def _booking_gift_value(agreement):
    """agreement -> presentation -> booking.gift_value_cents."""
    presentation = db.presentations.get(agreement["presentation_id"])
    if presentation is None:
        return 0
    booking = db.bookings.get(presentation["booking_id"])
    if booking is None:
        return 0
    return booking["gift_value_cents"]


@bp.post("/refund-disbursements/<disbursement_id>/settle")
def settle_disbursement(disbursement_id):
    auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    reference = validators.string(data, "settlement_reference", 1, 120)
    disbursement = get_refund(disbursement_id)
    if disbursement["status"] != "PENDING":
        fail(errors.ERR_INVALID_RESCISSION_REQUEST_STATE, "disbursement is not PENDING")

    now = db.now()
    derive.setf(disbursement, "status", "ISSUED")
    derive.setf(disbursement, "settlement_reference", reference)
    derive.setf(disbursement, "settled_at", now)

    request_record = db.rescissions.get(disbursement["rescission_request_id"])
    if request_record is not None:
        derive.setf(request_record, "status", "REFUNDED")
        agreement = db.agreements.get(request_record["agreement_id"])
        if agreement is not None:
            derive.setf(
                agreement,
                "retained_cents",
                disbursement["gift_recapture_cents"]
                + disbursement["doc_fee_retained_cents"],
            )
    return ok(disbursement)


@bp.get("/refund-disbursements/<disbursement_id>")
def read_disbursement(disbursement_id):
    auth.require_any()
    return ok(get_refund(disbursement_id))


@bp.get("/refund-disbursements")
def list_disbursements():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.refunds,
        (
            ("rescission_request_id", "rescission_request_id"),
            ("status", "status", REFUND_STATUSES),
        ),
    )
    return listing(rows, limit, offset)
