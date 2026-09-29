"""Public comment periods (PRD 3.7) and the half-open window convention (2.10)."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, serialize, set_fields
from errors import ApiError
from helpers import (
    all_periods_closed,
    compute_closes_at,
    fetch,
    fetch_fk,
    list_and_respond,
    move_review_axis,
    period_closes_dt,
    period_opens_dt,
    set_earliest_decision_at,
    windows_overlap,
)
from middleware import (
    ALL_ROLES,
    ROLE_ANALYST,
    get_body,
    opt_int,
    req_dt,
    req_str,
    require_roles,
)
from response import object_response

periods_bp = Blueprint("periods", __name__)


@periods_bp.post("/comment-periods")
@require_roles(ROLE_ANALYST)
def create_period():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    opens_dt = req_dt(body, "opens_at")
    duration_days = opt_int(
        body, "duration_days", minimum=7, maximum=90, default=calc.DEFAULT_COMMENT_DURATION_DAYS
    )

    application = fetch_fk("applications", application_id)

    record = new_record(
        {
            "application_id": application["id"],
            "opens_at": body["opens_at"],
            "duration_days": duration_days,
            "closes_at": None,
            "extension_count": 0,
            "extended_days_total": 0,
            "status": "OPEN",
            "comment_count": 0,
            "substantive_protest_count": 0,
        }
    )
    record["closes_at"] = compute_closes_at(record)
    new_closes = period_closes_dt(record)

    for existing in aggregates.application_periods(application["id"]):
        if windows_overlap(
            period_opens_dt(existing), period_closes_dt(existing), opens_dt, new_closes
        ):
            raise ApiError(
                "ERR_COMMENT_PERIOD_OVERLAP",
                "the interval overlaps an existing comment period of this application",
            )

    db.periods[record["id"]] = record
    move_review_axis(application, ("NOT_OPEN",), "OPEN_FOR_COMMENT")
    return object_response(serialize(record), 201)


@periods_bp.get("/comment-periods/<record_id>")
@require_roles(*ALL_ROLES)
def get_period(record_id):
    return object_response(serialize(fetch("periods", record_id)))


@periods_bp.get("/comment-periods")
@require_roles(*ALL_ROLES)
def list_periods():
    return list_and_respond("periods", ("application_id", "status"))


@periods_bp.post("/comment-periods/<record_id>/close")
@require_roles(ROLE_ANALYST)
def close_period(record_id):
    period = fetch("periods", record_id)
    get_body(required=False)
    if period["status"] not in ("OPEN", "EXTENDED"):
        raise ApiError("ERR_COMMENT_PERIOD_NOT_OPEN", "the comment period is already CLOSED")

    period_comment_ids = {c["id"] for c in aggregates.period_comments(period["id"])}
    for hearing in db.hearings.values():
        if hearing["status"] == "PENDING" and hearing["comment_id"] in period_comment_ids:
            raise ApiError(
                "ERR_HEARING_REQUEST_PENDING",
                "a hearing request citing a comment of this period is PENDING",
            )

    set_fields(period, status="CLOSED")
    application = db.applications.get(period["application_id"])
    if application is not None:
        set_earliest_decision_at(application, period_closes_dt(period))
        if all_periods_closed(application["id"]):
            move_review_axis(
                application,
                ("OPEN_FOR_COMMENT", "PROTEST_PENDING", "HEARING_GRANTED"),
                "COMMENT_CLOSED",
            )
    return object_response(serialize(period))
