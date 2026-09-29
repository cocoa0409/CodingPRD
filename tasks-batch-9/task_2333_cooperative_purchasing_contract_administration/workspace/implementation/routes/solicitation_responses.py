"""Supplier responses and their responsiveness dimension (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint

import services
from calc import num
from db import create_row, db, get_dt, logical_now, ordered, serialize
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_SUPPLIER, actor_id, commit, require_roles, touch)
from response import created_response, object_response
from routes.common import RESPONSE_STATUS, fetch, list_endpoint
from validation import json_body, read_dec, read_id, read_int, read_str

bp = Blueprint("solicitation_responses", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_AUDITOR)

REVIEW_ACTIONS = ("REQUEST_INFO", "MARK_RESPONSIVE", "MARK_NON_RESPONSIVE")
SUBMISSION_ACTIONS = ("RESUBMIT", "WITHDRAW")
LIVE_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "RESPONSIVE")
MAX_INFO_REQUEST_ROUNDS = 2


@bp.route("/coop/solicitation-responses", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def create_response():
    body = json_body(
        allowed=("solicitation_id", "supplier_id", "proposed_annual_value_cents",
                 "responsiveness_note"),
        required=("solicitation_id", "supplier_id", "proposed_annual_value_cents"),
    )
    solicitation_id = read_id(body, "solicitation_id", required=True)
    supplier_id = read_id(body, "supplier_id", required=True)
    value = read_int(body, "proposed_annual_value_cents", required=True, minimum=1)
    note = read_str(body, "responsiveness_note")

    # 5. body foreign keys in entity field order
    solicitation = fetch(db.solicitations, solicitation_id,
                         "ERR_SOLICITATION_NOT_FOUND")
    supplier = fetch(db.suppliers, supplier_id, "ERR_SUPPLIER_NOT_FOUND")

    # 7. entity-backed actor scope
    if actor_id() != supplier_id:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the supplier_id named in the body")

    # 13. responses may only be filed on a POSTED solicitation, before the deadline
    if solicitation["status"] != "POSTED":
        fail("ERR_SOLICITATION_CLOSED_FOR_RESPONSES",
             "the solicitation is not accepting responses")
    if logical_now() > get_dt(solicitation, "response_due_at"):
        fail("ERR_SOLICITATION_CLOSED_FOR_RESPONSES",
             "the response deadline has passed")

    # 25. the acting supplier must be QUALIFIED
    if supplier["qualification_status"] != "QUALIFIED":
        fail("ERR_SUPPLIER_NOT_QUALIFIED", "the supplier is not QUALIFIED")

    # 39. at most one live response per supplier per solicitation
    for existing in services.responses_of_solicitation(solicitation_id):
        if existing["supplier_id"] == supplier_id and existing["status"] in LIVE_STATUSES:
            fail("ERR_DUPLICATE_RESPONSE",
                 "this supplier already holds a live response on the solicitation")

    row = create_row(
        db.responses,
        solicitation_id=solicitation_id,
        supplier_id=supplier_id,
        status="SUBMITTED",
        proposed_annual_value_cents=value,
        technical_score=None,
        price_score=None,
        composite_score=None,
        award_rank=None,
        info_request_rounds=0,
        responsiveness_note=note,
    )
    return created_response(serialize(row))


@bp.route("/coop/solicitation-responses", methods=["GET"])
@require_roles(*READ_ROLES)
def list_responses():
    return list_endpoint(
        lambda: ordered(db.responses),
        {"solicitation_id": ("solicitation_id", None),
         "supplier_id": ("supplier_id", None),
         "status": ("status", RESPONSE_STATUS)},
    )


@bp.route("/coop/solicitation-responses/<response_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_response(response_id):
    row = fetch(db.responses, response_id, "ERR_RESPONSE_NOT_FOUND")
    return object_response(serialize(row))


@bp.route("/coop/solicitation-responses/<response_id>/review", methods=["POST"])
@require_roles(ROLE_LEAD_AGENCY)
def review(response_id):
    body = json_body(allowed=("action", "technical_score", "responsiveness_note"),
                     required=("action",))
    action = read_str(body, "action", required=True, enum=REVIEW_ACTIONS)
    raw_score = body.get("technical_score")
    if raw_score is not None and (isinstance(raw_score, bool)
                                 or not isinstance(raw_score, (int, float))):
        from validation import bad
        bad("field 'technical_score' must be a number")
    note = read_str(body, "responsiveness_note")

    response = fetch(db.responses, response_id, "ERR_RESPONSE_NOT_FOUND")
    solicitation = db.solicitations[response["solicitation_id"]]

    # 13. every evaluator action requires the solicitation to be in EVALUATION
    if solicitation["status"] != "EVALUATION":
        fail("ERR_SOLICITATION_INVALID_STATE",
             "the solicitation is not in EVALUATION")

    # 14. from-state on the responsiveness dimension
    status = response["status"]
    expected = {
        "REQUEST_INFO": ("SUBMITTED",),
        "MARK_RESPONSIVE": ("SUBMITTED",),
        "MARK_NON_RESPONSIVE": ("SUBMITTED", "INFO_REQUESTED", "RESPONSIVE"),
    }[action]
    if status not in expected:
        fail("ERR_RESPONSE_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    # 25. marking responsive requires a QUALIFIED supplier
    if action == "MARK_RESPONSIVE":
        supplier = db.suppliers[response["supplier_id"]]
        if supplier["qualification_status"] != "QUALIFIED":
            fail("ERR_SUPPLIER_NOT_QUALIFIED", "the supplier is not QUALIFIED")

        # 51. a technical score inside 0.00..100.00 is mandatory
        if raw_score is None:
            fail("ERR_TECHNICAL_SCORE_MISSING", "technical_score is required")
        score = Decimal(str(raw_score))
        if score < Decimal("0") or score > Decimal("100"):
            fail("ERR_TECHNICAL_SCORE_MISSING",
                 "technical_score must be between 0.00 and 100.00")

    # 52. bounded information-request rounds
    if action == "REQUEST_INFO":
        if int(response["info_request_rounds"]) >= MAX_INFO_REQUEST_ROUNDS:
            fail("ERR_INFO_REQUEST_ROUNDS_EXHAUSTED",
                 "the information-request allowance is exhausted")

    if action == "REQUEST_INFO":
        response["status"] = "INFO_REQUESTED"
        if note is not None:
            response["responsiveness_note"] = note
    elif action == "MARK_RESPONSIVE":
        response["status"] = "RESPONSIVE"
        response["technical_score"] = num(Decimal(str(raw_score)))
        if note is not None:
            response["responsiveness_note"] = note
        solicitation["responsive_response_count"] = int(
            solicitation["responsive_response_count"]) + 1
        touch(solicitation)
    else:  # MARK_NON_RESPONSIVE
        was_responsive = status == "RESPONSIVE"
        response["status"] = "NON_RESPONSIVE"
        if note is not None:
            response["responsiveness_note"] = note
        if was_responsive:
            solicitation["responsive_response_count"] = max(
                0, int(solicitation["responsive_response_count"]) - 1)
            touch(solicitation)
            response["technical_score"] = None
            response["price_score"] = None
            response["composite_score"] = None
            response["award_rank"] = None

    touch(response)
    commit()
    return object_response(serialize(response))


@bp.route("/coop/solicitation-responses/<response_id>/submission", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def submission(response_id):
    body = json_body(allowed=("action", "note", "responsiveness_note"),
                     required=("action",))
    action = read_str(body, "action", required=True, enum=SUBMISSION_ACTIONS)
    read_str(body, "note")
    note = read_str(body, "responsiveness_note")

    response = fetch(db.responses, response_id, "ERR_RESPONSE_NOT_FOUND")

    # 7. the acting supplier must own the response
    if actor_id() != response["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the response's supplier_id")

    solicitation = db.solicitations[response["solicitation_id"]]

    # 13. the solicitation must permit the action
    if action == "RESUBMIT":
        if solicitation["status"] != "EVALUATION":
            fail("ERR_SOLICITATION_INVALID_STATE",
                 "the solicitation is not in EVALUATION")
    else:  # WITHDRAW
        if solicitation["status"] not in ("POSTED", "EVALUATION"):
            fail("ERR_SOLICITATION_INVALID_STATE",
                 "the solicitation must be POSTED or in EVALUATION")

    # 14. from-state on the responsiveness dimension
    status = response["status"]
    expected = {
        "RESUBMIT": ("INFO_REQUESTED",),
        "WITHDRAW": ("SUBMITTED", "INFO_REQUESTED"),
    }[action]
    if status not in expected:
        fail("ERR_RESPONSE_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    if action == "RESUBMIT":
        response["status"] = "SUBMITTED"
        response["info_request_rounds"] = int(response["info_request_rounds"]) + 1
        if note is not None:
            response["responsiveness_note"] = note
    else:
        response["status"] = "WITHDRAWN"

    touch(response)
    commit()
    return object_response(serialize(response))
