"""Participation plans, public meetings and public comments."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import serialize
from db import clock_date, db, new_row, touch
from errors import ApiError, bad_request
from middleware import authenticate
from response import list_response, object_response, paginate
from services import cascade, repo
from validators import (body_json, f_bool, f_instant, f_lang, f_lang_array,
                        f_date, f_int, f_str, q_enum, q_pagination, q_str)

bp = Blueprint("participation", __name__)


def _capacity_guard(plan, area, start_date, end_date):
    concurrent = cascade.area_engagement_conflicts(plan, area, start_date, end_date)
    if concurrent + 1 > cascade.engagement_cap(area):
        raise ApiError("ERR_AREA_ENGAGEMENT_CAPACITY")


def _area_of_plan(plan):
    application = db.permit_applications[plan["permit_application_id"]]
    return repo.area_of_application(application)


# --------------------------------------------------------------------------- reads
@bp.get("/ej/participation-plans/<plan_id>")
def read_plan(plan_id):
    authenticate(C.READ_NO_INSPECTOR)
    plan = repo.get_plan(plan_id)
    return object_response(serialize.participation_plan(plan))


@bp.get("/ej/permit-applications/<application_id>/participation-plans")
def list_application_plans(application_id):
    authenticate(C.READ_NO_INSPECTOR)
    limit, offset = q_pagination()
    application = repo.get_application(application_id)
    rows = repo.plans_of(application["id"])
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.participation_plan, page),
                         limit, offset, total)


# ---------------------------------------------------------------------- plan writes
@bp.patch("/ej/participation-plans/<plan_id>")
def patch_plan(plan_id):
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body = body_json()
    translated_languages = f_lang_array(body, "translated_languages", required=False,
                                        default=None)
    materials_translated = f_bool(body, "materials_translated", required=False)

    plan = repo.get_plan(plan_id)
    if plan["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_PLAN_STATE")

    if "translated_languages" in body and body["translated_languages"] is not None:
        plan["translated_languages"] = translated_languages
    if materials_translated is not None:
        plan["materials_translated"] = materials_translated
    touch(plan)
    return object_response(serialize.participation_plan(plan))


@bp.post("/ej/participation-plans/<plan_id>/open")
def open_plan(plan_id):
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body = body_json()
    comment_start_date = f_date(body, "comment_start_date")

    plan = repo.get_plan(plan_id)
    if plan["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if comment_start_date < clock_date():
        raise ApiError("ERR_COMMENT_START_IN_PAST")

    span = plan["required_comment_days"] + plan["granted_extension_days"]
    comment_end_date = comment_start_date + timedelta(days=span - 1)

    area = _area_of_plan(plan)
    _capacity_guard(plan, area, comment_start_date, comment_end_date)

    plan["comment_start_date"] = comment_start_date
    plan["comment_end_date"] = comment_end_date
    plan["status"] = "OPEN"
    touch(plan)
    area["open_plan_count"] = area["open_plan_count"] + 1
    touch(area)
    return object_response(serialize.participation_plan(plan))


@bp.post("/ej/participation-plans/<plan_id>/extend")
def extend_plan(plan_id):
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body = body_json()
    additional_days = f_int(body, "additional_days", minimum=1)
    f_str(body, "reason", min_len=1)

    plan = repo.get_plan(plan_id)
    if plan["status"] not in ("OPEN", "EXTENDED"):
        raise ApiError("ERR_INVALID_PLAN_STATE")

    projected = (plan["required_comment_days"] + plan["granted_extension_days"]
                 + additional_days)
    if projected > C.MAX_COMMENT_DAYS:
        raise ApiError("ERR_COMMENT_DAYS_CAP_EXCEEDED")

    candidate_end = plan["comment_end_date"] + timedelta(days=additional_days)
    area = _area_of_plan(plan)
    _capacity_guard(plan, area, plan["comment_start_date"], candidate_end)

    plan["granted_extension_days"] = plan["granted_extension_days"] + additional_days
    plan["comment_end_date"] = candidate_end
    plan["status"] = "EXTENDED"
    touch(plan)
    return object_response(serialize.participation_plan(plan))


@bp.post("/ej/participation-plans/<plan_id>/close")
def close_plan(plan_id):
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body_json()
    plan = repo.get_plan(plan_id)
    if plan["status"] not in ("OPEN", "EXTENDED"):
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if not (plan["comment_end_date"] is not None
            and clock_date() > plan["comment_end_date"]):
        raise ApiError("ERR_COMMENT_PERIOD_NOT_ELAPSED")

    area = _area_of_plan(plan)
    plan["status"] = "CLOSED"
    cascade.participation_adequacy(plan, area)
    touch(plan)
    area["open_plan_count"] = area["open_plan_count"] - 1
    touch(area)
    return object_response(serialize.participation_plan(plan))


# ------------------------------------------------------------------------ meetings
@bp.post("/ej/public-meetings")
def create_meeting():
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body = body_json()
    participation_plan_id = f_str(body, "participation_plan_id")
    venue_id = f_str(body, "venue_id")
    starts_raw, starts_at = f_instant(body, "starts_at")
    ends_raw, ends_at = f_instant(body, "ends_at")
    languages = f_lang_array(body, "interpretation_languages", required=False,
                             default=[])
    if ends_at <= starts_at:
        raise bad_request("Field 'ends_at' must be strictly later than 'starts_at'.")

    plan = repo.get_plan(participation_plan_id)
    venue = repo.get_venue(venue_id)

    window_start = plan["comment_start_date"]
    window_end = plan["comment_end_date"]
    inside = (
        window_start is not None
        and window_end is not None
        and window_start <= starts_at.date() <= window_end
        and window_start <= ends_at.date() <= window_end
    )
    if not inside:
        raise ApiError("ERR_MEETING_OUTSIDE_COMMENT_WINDOW")
    if venue["status"] != "ACTIVE":
        raise ApiError("ERR_VENUE_DECOMMISSIONED")
    if not (venue["ada_accessible"] and venue["transit_accessible"]):
        raise ApiError("ERR_VENUE_NOT_ACCESSIBLE")
    if cascade.venue_slot_conflict(venue["id"], starts_at, ends_at):
        raise ApiError("ERR_VENUE_SLOT_CONFLICT")

    row = new_row()
    row.update(
        {
            "participation_plan_id": plan["id"],
            "venue_id": venue["id"],
            "starts_at": starts_raw,
            "ends_at": ends_raw,
            "_starts_at": starts_at,
            "_ends_at": ends_at,
            "interpretation_languages": languages,
            "accessibility_verified": bool(
                venue["ada_accessible"] and venue["transit_accessible"]
            ),
            "status": "SCHEDULED",
        }
    )
    db.public_meetings[row["id"]] = row

    venue["booked_meeting_count"] = venue["booked_meeting_count"] + 1
    touch(venue)
    plan["meeting_count"] = plan["meeting_count"] + 1
    touch(plan)
    return object_response(serialize.public_meeting(row), 201)


@bp.get("/ej/participation-plans/<plan_id>/meetings")
def list_plan_meetings(plan_id):
    authenticate(C.READ_NO_INSPECTOR)
    limit, offset = q_pagination()
    status = q_enum("status", C.MEETING_STATUSES)
    plan = repo.get_plan(plan_id)
    rows = repo.meetings_of_plan(plan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.public_meeting, page),
                         limit, offset, total)


@bp.post("/ej/public-meetings/<meeting_id>/cancel")
def cancel_meeting(meeting_id):
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body = body_json()
    f_str(body, "reason", required=False)

    meeting = repo.get_meeting(meeting_id)
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_MEETING_STATE")

    meeting["status"] = "CANCELLED"
    touch(meeting)

    venue = db.venues[meeting["venue_id"]]
    venue["booked_meeting_count"] = venue["booked_meeting_count"] - 1
    touch(venue)

    plan = db.participation_plans[meeting["participation_plan_id"]]
    plan["meeting_count"] = plan["meeting_count"] - 1
    touch(plan)
    return object_response(serialize.public_meeting(meeting))


# ------------------------------------------------------------------------ comments
@bp.post("/ej/public-comments")
def create_comment():
    authenticate((C.ROLE_PUBLIC_COMMENTER, C.ROLE_COMMUNITY_LIAISON))
    body = body_json()
    participation_plan_id = f_str(body, "participation_plan_id")
    submitter_name = f_str(body, "submitter_name", min_len=1)
    language = f_lang(body, "language")
    text = f_str(body, "body", min_len=1, max_len=4000)
    requires_response = f_bool(body, "requires_response", required=False, default=False)

    plan = repo.get_plan(participation_plan_id)

    today = clock_date()
    open_now = (
        plan["status"] in ("OPEN", "EXTENDED")
        and plan["comment_start_date"] is not None
        and plan["comment_end_date"] is not None
        and plan["comment_start_date"] <= today <= plan["comment_end_date"]
    )
    if not open_now:
        raise ApiError("ERR_COMMENT_PERIOD_CLOSED")

    row = new_row(full_audit=False)
    row.update(
        {
            "participation_plan_id": plan["id"],
            "submitter_name": submitter_name,
            "language": language,
            "body": text,
            "requires_response": requires_response,
            "in_required_language": bool(
                language == "en" or language in plan["translated_languages"]
            ),
        }
    )
    db.public_comments[row["id"]] = row

    plan["comment_count"] = plan["comment_count"] + 1
    touch(plan)
    return object_response(serialize.public_comment(row), 201)


@bp.get("/ej/participation-plans/<plan_id>/comments")
def list_plan_comments(plan_id):
    authenticate(C.READ_NO_INSPECTOR)
    limit, offset = q_pagination()
    language = q_str("language")
    plan = repo.get_plan(plan_id)
    rows = repo.comments_of_plan(plan["id"])
    if language is not None:
        rows = [r for r in rows if r["language"] == language]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.public_comment, page),
                         limit, offset, total)
