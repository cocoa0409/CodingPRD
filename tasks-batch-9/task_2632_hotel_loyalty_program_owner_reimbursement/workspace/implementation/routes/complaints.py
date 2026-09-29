"""Member complaints, the bounded review loop and programme adjudication."""

from flask import Blueprint, request

import db
import middleware
import support
import validate
from errors import ApiError
from middleware import ADMIN, AGENT, AUDITOR, MEMBER
from services import calc, derive

bp = Blueprint("complaints", __name__)


def _delivery_of(complaint):
    identifier = complaint.get("related_delivery_id")
    if identifier is None:
        return None
    return db.store.deliveries.get(identifier)


def _hotel_of(delivery):
    stay = db.store.stays.get(delivery["stay_id"]) if delivery else None
    if stay is None:
        return None, None
    return stay, db.store.hotels.get(stay["hotel_id"])


@bp.route("/loyalty/member-complaints", methods=["POST"])
def create_complaint():
    caller = middleware.require(MEMBER, AGENT, ADMIN)
    payload = validate.body()
    member_id = validate.fk(payload, "member_id")
    middleware.own_member(caller, member_id)
    validate.get_member(member_id)
    delivery_id = validate.opt_fk(payload, "related_delivery_id")
    delivery = validate.get_delivery(delivery_id) if delivery_id is not None else None

    subject_type = validate.req_enum(payload, "subject_type", calc.COMPLAINT_SUBJECTS)
    description = validate.req_str(payload, "description", 1, 2000)

    if subject_type == "BENEFIT_DENIAL":
        if delivery is None:
            raise ApiError("ERR_DELIVERY_MEMBER_MISMATCH",
                           "A benefit-denial complaint must name the disputed obligation.")
    if delivery is not None:
        stay = db.store.stays.get(delivery["stay_id"])
        if stay is None or stay["member_id"] != member_id:
            raise ApiError("ERR_DELIVERY_MEMBER_MISMATCH")

    record = {}
    db.stamp_full(record)
    record.update({
        "member_id": member_id,
        "related_delivery_id": delivery["id"] if (
            delivery is not None and subject_type == "BENEFIT_DENIAL") else None,
        "subject_type": subject_type,
        "description": description,
        "status": "OPEN",
        "info_request_count": 0,
        "goodwill_points_granted": 0,
        "resolution": None,
        "adjudication_outcome": None,
    })
    support.tail(record)
    db.store.complaints[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/member-complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    complaint = validate.get_complaint(complaint_id)
    middleware.own_member(caller, complaint["member_id"])
    return support.one(complaint)


@bp.route("/loyalty/member-complaints", methods=["GET"])
def list_complaints():
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    middleware.scope_filter(caller, request.args, hotel_key=None)
    extra = None
    if caller.is_member:
        extra = lambda r: r["member_id"] == caller.user_id
    return support.listing(
        db.store.complaints.values(),
        ("member_id", "related_delivery_id", "status", "subject_type"), extra)


# ---------------------------------------------------------------------------
# the review loop
# ---------------------------------------------------------------------------

@bp.route("/loyalty/member-complaints/<complaint_id>/review", methods=["POST"])
def review_complaint(complaint_id):
    middleware.require(AGENT, ADMIN)
    complaint = validate.get_complaint(complaint_id)
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Only an open complaint may be taken under review.")
    complaint["status"] = "UNDER_REVIEW"
    db.touch(complaint)
    return support.one(complaint)


@bp.route("/loyalty/member-complaints/<complaint_id>/request-info", methods=["POST"])
def request_info(complaint_id):
    middleware.require(AGENT)
    complaint = validate.get_complaint(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Only a complaint under review may be sent back for information.")
    if complaint["info_request_count"] >= calc.INFO_REQUEST_LIMIT:
        raise ApiError("ERR_INFO_REQUEST_LIMIT")
    complaint["status"] = "INFO_REQUESTED"
    complaint["info_request_count"] = complaint["info_request_count"] + 1
    db.touch(complaint)
    return support.one(complaint)


@bp.route("/loyalty/member-complaints/<complaint_id>/provide-info", methods=["POST"])
def provide_info(complaint_id):
    caller = middleware.require(MEMBER, AGENT)
    complaint = validate.get_complaint(complaint_id)
    middleware.own_member(caller, complaint["member_id"])
    payload = validate.body()
    description = validate.opt_str(payload, "description", 1, 2000)
    if complaint["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Only a complaint awaiting information may be answered.")
    complaint["status"] = "UNDER_REVIEW"
    if description is not None:
        complaint["description"] = description
    db.touch(complaint)
    return support.one(complaint)


@bp.route("/loyalty/member-complaints/<complaint_id>/resolve", methods=["POST"])
def resolve_complaint(complaint_id):
    middleware.require(AGENT, ADMIN)
    complaint = validate.get_complaint(complaint_id)
    payload = validate.body()
    resolution = validate.req_str(payload, "resolution", 1)
    goodwill = validate.opt_int(payload, "goodwill_points", 0)
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Only a complaint under review may be resolved.")
    if goodwill > 0 and derive.fund_is_impaired():
        raise ApiError("ERR_FUND_IMPAIRED")

    complaint["resolution"] = resolution
    if goodwill > 0:
        complaint["status"] = "RESOLVED_GOODWILL"
        complaint["goodwill_points_granted"] = goodwill
        db.touch(complaint)
        derive.add_entry(complaint["member_id"], "GOODWILL", goodwill)
        member = db.store.members.get(complaint["member_id"])
        if member is not None:
            derive.recompute_member(member)
        derive.recompute_fund()
    else:
        complaint["status"] = "RESOLVED_UPHELD"
        db.touch(complaint)
    return support.one(complaint)


# ---------------------------------------------------------------------------
# escalation and adjudication
# ---------------------------------------------------------------------------

@bp.route("/loyalty/member-complaints/<complaint_id>/escalate", methods=["POST"])
def escalate_complaint(complaint_id):
    caller = middleware.require(MEMBER, AGENT)
    complaint = validate.get_complaint(complaint_id)
    middleware.own_member(caller, complaint["member_id"])
    if complaint["status"] != "RESOLVED_UPHELD":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Only an upheld complaint may be escalated.")
    delivery = _delivery_of(complaint)
    if complaint["subject_type"] == "BENEFIT_DENIAL":
        if delivery is None or delivery["status"] != "DENIED":
            raise ApiError("ERR_DELIVERY_NOT_DENIED")

    complaint["status"] = "ESCALATED"
    db.touch(complaint)
    if complaint["subject_type"] == "BENEFIT_DENIAL" and delivery is not None:
        delivery["status"] = "ESCALATED"
        db.touch(delivery)
        _, hotel = _hotel_of(delivery)
        if hotel is not None:
            derive.recompute_hotel(hotel)
    return support.one(complaint)


@bp.route("/loyalty/member-complaints/<complaint_id>/adjudicate", methods=["POST"])
def adjudicate_complaint(complaint_id):
    middleware.require(ADMIN)
    complaint = validate.get_complaint(complaint_id)
    payload = validate.body()
    outcome = validate.req_enum(payload, "adjudication_outcome",
                                calc.ADJUDICATION_OUTCOMES)
    if complaint["status"] != "ESCALATED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Only an escalated complaint may be adjudicated.")
    delivery = _delivery_of(complaint)
    if complaint["subject_type"] == "BENEFIT_DENIAL":
        if delivery is None or delivery["status"] != "ESCALATED":
            raise ApiError("ERR_DELIVERY_NOT_ESCALATED")

    complaint["status"] = "CLOSED"
    complaint["adjudication_outcome"] = outcome
    db.touch(complaint)

    if complaint["subject_type"] == "BENEFIT_DENIAL" and delivery is not None:
        stay, hotel = _hotel_of(delivery)
        if outcome == "DELIVERY_ORDERED":
            delivery["status"] = "DELIVERED"
            delivery["cost_recovery_cents"] = calc.benefit_cost_recovery(
                delivery["benefit_type"], hotel or {}, stay or {})
        else:
            delivery["status"] = "DENIED_FINAL"
            delivery["cost_recovery_cents"] = 0
        db.touch(delivery)
        if hotel is not None:
            derive.recompute_hotel(hotel)
    return support.one(complaint)
