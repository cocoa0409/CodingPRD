"""State examination inquiries and their cyclic response rounds (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint

import serializers
from db import create, db, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, endpoint
from response import created, ok, paginated
from routes.common import filters, gate, get_or_404, get_referenced, listing, matches
from validators import Body, STATE_RE, body_fk, raw_body

bp = Blueprint("exams", __name__)

ROUND_LIMIT = 3
INFO_REQUEST_EXTENSION_DAYS = 14


@bp.route("/examination-inquiries", methods=["POST"])
@endpoint("ExaminationCoordinator")
def record_inquiry():
    raw = raw_body()
    originator_ref = body_fk(raw, "originator_id")
    originator = None
    if originator_ref is not None:
        originator = get_referenced(db.originators, originator_ref)
    body = Body(raw)
    state_code = body.string("state_code", pattern=STATE_RE)
    exam_reference = body.string("exam_reference", min_len=4, max_len=32)
    response_due_at = body.datetime("response_due_at")
    if not response_due_at > db.clock:
        raise bad_request("response_due_at must fall strictly after the current instant.")

    for row in db.examination_inquiries.values():
        if row["exam_reference"] == exam_reference:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = create(db.examination_inquiries, {
        "originator_id": originator["id"] if originator is not None else None,
        "state_code": state_code,
        "exam_reference": exam_reference,
        "opened_at": db.clock,
        "response_due_at": response_due_at,
        "status": "OPEN",
        "response_round_count": 0,
        "last_response_at": None,
        "escalation_reason": None,
    })
    return created(serializers.examination_inquiry(row))


@bp.route("/examination-inquiries", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_inquiries():
    active = filters("originator_id", "state_code", "status")
    rows = listing(db.examination_inquiries, lambda r: matches(r, active))
    return paginated(rows, serializers.examination_inquiry)


@bp.route("/examination-inquiries/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_inquiry(row_id):
    row = get_or_404(db.examination_inquiries, row_id)
    return ok(serializers.examination_inquiry(row))


@bp.route("/examination-inquiries/<row_id>/responses", methods=["POST"])
@endpoint("ExaminationCoordinator")
def file_response(row_id):
    inquiry = get_or_404(db.examination_inquiries, row_id)
    body = Body(raw_body())
    body.string("narrative", max_len=8000)
    gate("ExaminationInquiry", inquiry, ("OPEN", "INFO_REQUESTED"))
    if db.clock > inquiry["response_due_at"]:
        raise ApiError("ERR_RESPONSE_DEADLINE_PASSED")
    inquiry["status"] = "RESPONSE_SUBMITTED"
    # Every entry into RESPONSE_SUBMITTED counts, cyclic re-entries included.
    inquiry["response_round_count"] = inquiry["response_round_count"] + 1
    inquiry["last_response_at"] = db.clock
    touch(inquiry)
    return ok(serializers.examination_inquiry(inquiry))


@bp.route("/examination-inquiries/<row_id>/info-requests", methods=["POST"])
@endpoint("ExaminationCoordinator")
def request_info(row_id):
    inquiry = get_or_404(db.examination_inquiries, row_id)
    body = Body(raw_body())
    body.string("request_note", max_len=8000)
    gate("ExaminationInquiry", inquiry, ("RESPONSE_SUBMITTED",))
    if inquiry["response_round_count"] < ROUND_LIMIT:
        inquiry["status"] = "INFO_REQUESTED"
        inquiry["response_due_at"] = db.clock + timedelta(days=INFO_REQUEST_EXTENSION_DAYS)
    else:
        inquiry["status"] = "ESCALATED"
        inquiry["escalation_reason"] = "ROUND_LIMIT_REACHED"
    touch(inquiry)
    return ok(serializers.examination_inquiry(inquiry))


@bp.route("/examination-inquiries/<row_id>/close", methods=["POST"])
@endpoint("ExaminationCoordinator")
def close_inquiry(row_id):
    inquiry = get_or_404(db.examination_inquiries, row_id)
    gate("ExaminationInquiry", inquiry, ("RESPONSE_SUBMITTED", "ESCALATED"))
    inquiry["status"] = "CLOSED"
    touch(inquiry)
    return ok(serializers.examination_inquiry(inquiry))
