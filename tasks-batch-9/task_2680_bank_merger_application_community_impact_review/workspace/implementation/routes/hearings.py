"""Hearing petitions and the divergent grant / denial cascades (PRD 3.8)."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, now_str, serialize, set_fields
from errors import ApiError
from helpers import (
    compute_closes_at,
    fetch,
    fetch_fk,
    list_and_respond,
    move_review_axis,
    period_closes_dt,
    set_earliest_decision_at,
)
from middleware import (
    ALL_ROLES,
    ROLE_COMMENTER,
    ROLE_OFFICIAL,
    actor_id,
    get_body,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response

hearings_bp = Blueprint("hearings", __name__)

OUTCOMES = ("GRANTED", "DENIED")


@hearings_bp.post("/hearing-requests")
@require_roles(ROLE_COMMENTER)
def create_hearing_request():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    comment_id = req_str(body, "comment_id")
    basis = req_str(body, "basis", min_len=1, max_len=2000)

    application = fetch_fk("applications", application_id)
    comment = fetch_fk("comments", comment_id)
    period = db.periods.get(comment["period_id"])
    if period is None:
        raise ApiError("ERR_COMMENT_PERIOD_NOT_FOUND", "the cited comment has no period")

    if period["status"] not in ("OPEN", "EXTENDED"):
        raise ApiError(
            "ERR_COMMENT_PERIOD_NOT_OPEN", "the cited comment's period is not open"
        )
    if not (
        comment["stance"] == "PROTEST"
        and bool(comment["substantive"])
        and comment["status"] in aggregates.PROTEST_COUNTED_STATUSES
        and int(period["substantive_protest_count"]) >= 1
    ):
        raise ApiError(
            "ERR_NO_SUBSTANTIVE_PROTEST",
            "the petition must cite a live substantive protest",
        )

    record = new_record(
        {
            "application_id": application["id"],
            "comment_id": comment["id"],
            "requester_user_id": actor_id(),
            "requested_at": now_str(),
            "basis": basis,
            "status": "PENDING",
            "decided_at": None,
            "decided_by_user_id": None,
            "decision_rationale": None,
            "extension_days_granted": 0,
        }
    )
    db.hearings[record["id"]] = record
    move_review_axis(application, ("PROTEST_PENDING",), "HEARING_PENDING")
    return object_response(serialize(record), 201)


@hearings_bp.get("/hearing-requests/<record_id>")
@require_roles(*ALL_ROLES)
def get_hearing_request(record_id):
    return object_response(serialize(fetch("hearings", record_id)))


@hearings_bp.get("/hearing-requests")
@require_roles(*ALL_ROLES)
def list_hearing_requests():
    return list_and_respond("hearings", ("application_id", "comment_id", "status"))


def _axis_fallback(application, hearing):
    """Denial and withdrawal share the same fallback (PRD 3.8)."""
    if aggregates.has_pending_hearing(application["id"], exclude_id=hearing["id"]):
        return
    if int(application["unresolved_protest_count"]) >= 1:
        move_review_axis(application, ("HEARING_PENDING",), "PROTEST_PENDING")
    else:
        move_review_axis(application, ("HEARING_PENDING",), "OPEN_FOR_COMMENT")


@hearings_bp.post("/hearing-requests/<record_id>/decide")
@require_roles(ROLE_OFFICIAL)
def decide_hearing_request(record_id):
    hearing = fetch("hearings", record_id)
    body = get_body(required=True)
    outcome = req_enum(body, "outcome", OUTCOMES)
    rationale = req_str(body, "decision_rationale", min_len=1)

    if hearing["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_HEARING_REQUEST_STATE", "only a PENDING petition can be ruled on"
        )
    application = db.applications.get(hearing["application_id"])
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the petition's application is unknown")
    if application["filing_status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the application must be UNDER_REVIEW to rule on a petition",
        )
    comment = db.comments.get(hearing["comment_id"])
    period = db.periods.get(comment["period_id"]) if comment else None

    if outcome == "GRANTED":
        if period is None or period["status"] not in ("OPEN", "EXTENDED"):
            raise ApiError(
                "ERR_COMMENT_PERIOD_NOT_OPEN", "the cited comment's period is not open"
            )
        # cascade link 1
        set_fields(
            hearing,
            status="GRANTED",
            decided_at=now_str(),
            decided_by_user_id=actor_id(),
            decision_rationale=rationale,
            extension_days_granted=calc.HEARING_EXTENSION_DAYS,
        )
        # cascade link 2 — caused by link 1
        period["extended_days_total"] = (
            int(period["extended_days_total"]) + calc.HEARING_EXTENSION_DAYS
        )
        period["extension_count"] = int(period["extension_count"]) + 1
        period["closes_at"] = compute_closes_at(period)
        set_fields(period, status="EXTENDED")
        from db import touch

        touch(period)
        # cascade link 3 — caused by link 2
        set_earliest_decision_at(application, period_closes_dt(period))
        move_review_axis(application, ("HEARING_PENDING",), "HEARING_GRANTED")
        return object_response(serialize(hearing))

    set_fields(
        hearing,
        status="DENIED",
        decided_at=now_str(),
        decided_by_user_id=actor_id(),
        decision_rationale=rationale,
    )
    _axis_fallback(application, hearing)
    return object_response(serialize(hearing))


@hearings_bp.post("/hearing-requests/<record_id>/withdraw")
@require_roles(ROLE_COMMENTER)
def withdraw_hearing_request(record_id):
    hearing = fetch("hearings", record_id)
    get_body(required=False)
    if actor_id() != hearing["requester_user_id"]:
        raise ApiError(
            "ERR_NOT_REQUEST_OWNER", "only the original requester may withdraw the petition"
        )
    if hearing["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_HEARING_REQUEST_STATE", "only a PENDING petition can be withdrawn"
        )
    set_fields(hearing, status="WITHDRAWN")
    application = db.applications.get(hearing["application_id"])
    if application is not None:
        _axis_fallback(application, hearing)
    return object_response(serialize(hearing))
