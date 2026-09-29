"""Public comments and the filer's response (PRD 3.7)."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, now_str, serialize, set_fields
from errors import ApiError
from helpers import (
    ensure_application_filer,
    fetch,
    fetch_fk,
    list_and_respond,
    move_review_axis,
    now,
    period_closes_dt,
    _days,
)
from middleware import (
    ALL_ROLES,
    ROLE_COMMENTER,
    ROLE_FILER,
    actor_id,
    get_body,
    opt_bool,
    opt_str,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response

comments_bp = Blueprint("comments", __name__)

COMMENTER_TYPES = ("INDIVIDUAL", "COMMUNITY_ORGANIZATION", "TRADE_GROUP", "GOVERNMENT")
STANCES = ("SUPPORT", "OPPOSE", "PROTEST")
DISPOSITIONS = ("ACKNOWLEDGED", "RESPONDED")


@comments_bp.post("/public-comments")
@require_roles(ROLE_COMMENTER)
def create_comment():
    body = get_body(required=True)
    period_id = req_str(body, "period_id")
    commenter_name = req_str(body, "commenter_name", min_len=1)
    commenter_type = req_enum(body, "commenter_type", COMMENTER_TYPES)
    stance = req_enum(body, "stance", STANCES)
    text = req_str(body, "body", min_len=1, max_len=4000)
    substantive = opt_bool(body, "substantive", default=False)

    period = fetch_fk("periods", period_id)

    instant = now()
    closes = period_closes_dt(period)
    if instant < closes:
        status = "RECEIVED"
    elif instant < closes + _days(calc.COMMENT_GRACE_DAYS):
        status = "UNTIMELY"
    else:
        raise ApiError(
            "ERR_COMMENT_WINDOW_CLOSED",
            "the comment window and its grace tail have expired",
        )

    record = new_record(
        {
            "period_id": period["id"],
            "commenter_user_id": actor_id(),
            "commenter_name": commenter_name,
            "commenter_type": commenter_type,
            "stance": stance,
            "substantive": bool(substantive),
            "body": text,
            "received_at": now_str(),
            "status": status,
            "response_body": None,
            "responded_at": None,
        }
    )
    db.comments[record["id"]] = record

    aggregates.recompute_period_counters(period)
    application = db.applications.get(period["application_id"])
    if application is not None:
        aggregates.recompute_application_protest_counts(application)
        if (
            status == "RECEIVED"
            and stance == "PROTEST"
            and substantive
            and int(application["substantive_protest_count"]) >= 1
        ):
            move_review_axis(application, ("OPEN_FOR_COMMENT",), "PROTEST_PENDING")
    return object_response(serialize(record), 201)


@comments_bp.get("/public-comments/<record_id>")
@require_roles(*ALL_ROLES)
def get_comment(record_id):
    return object_response(serialize(fetch("comments", record_id)))


@comments_bp.get("/public-comments")
@require_roles(*ALL_ROLES)
def list_comments():
    return list_and_respond("comments", ("period_id", "stance", "status"))


@comments_bp.post("/public-comments/<record_id>/respond")
@require_roles(ROLE_FILER)
def respond_to_comment(record_id):
    comment = fetch("comments", record_id)
    body = get_body(required=True)
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    response_body = opt_str(body, "response_body", default=None)

    period = db.periods.get(comment["period_id"])
    application = db.applications.get(period["application_id"]) if period else None
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the comment's application is unknown")
    ensure_application_filer(application)

    if disposition == "ACKNOWLEDGED":
        if comment["status"] != "RECEIVED":
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "only a RECEIVED comment can be acknowledged",
            )
        set_fields(comment, status="ACKNOWLEDGED", responded_at=now_str())
    else:
        if comment["status"] not in ("RECEIVED", "ACKNOWLEDGED"):
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "only a RECEIVED or ACKNOWLEDGED comment can be responded to",
            )
        if response_body is None or not response_body.strip():
            raise ApiError(
                "ERR_RESPONSE_BODY_REQUIRED", "a full response requires response_body"
            )
        set_fields(
            comment,
            status="RESPONDED",
            response_body=response_body,
            responded_at=now_str(),
        )

    aggregates.recompute_period_counters(period)
    aggregates.recompute_application_protest_counts(application)
    if disposition == "RESPONDED":
        if (
            int(application["unresolved_protest_count"]) == 0
            and not aggregates.has_pending_hearing(application["id"])
            and period["status"] in ("OPEN", "EXTENDED")
        ):
            move_review_axis(application, ("PROTEST_PENDING",), "OPEN_FOR_COMMENT")
    return object_response(serialize(comment))
