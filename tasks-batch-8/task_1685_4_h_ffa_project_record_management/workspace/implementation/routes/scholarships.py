"""Scholarship applications (PRD 3.9)."""

from flask import Blueprint, request

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_common_fields, touch)
from validation import (get_body, pagination_params, paginate,
                        sort_by_creation, present)
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_REFERENTIAL_INTEGRITY)
from services import calc
from services.serialize import scholarship_app_view

bp = Blueprint("scholarship_apps", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]
GRANT_MIN_POINTS = 30


@bp.post("/scholarship-apps")
def create_scholarship_app():
    role, user_id = authenticate(["Member"])
    body = get_body()
    # Priority 3: referenced identifiers exist, left-to-right
    # (member_id, linked_award_application_id).
    member = None
    linked = None
    if isinstance(body.get("member_id"), str):
        member = must_find("members", body["member_id"], "Member")
    if isinstance(body.get("linked_award_application_id"), str):
        linked = must_find("award_applications", body["linked_award_application_id"],
                           "AwardApplication")
    resolve_caller(role, user_id)
    # Priority 4: a member opens their own scholarship application.
    if isinstance(body.get("member_id"), str):
        require_member_ownership(user_id, body["member_id"])
    # Priority 13: referential integrity -- the linked application must belong
    # to the same member and be on the SCHOLARSHIP award track.
    if member is not None and linked is not None:
        if linked["member_id"] != member["id"] or linked["award_track"] != "SCHOLARSHIP":
            raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                           "The linked award application must belong to the same member and be on the SCHOLARSHIP track")
    # Priority 14: request shape.
    member_id = present(body, "member_id")
    if not isinstance(member_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'member_id': must be a string")
    linked_id = present(body, "linked_award_application_id")
    if not isinstance(linked_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'linked_award_application_id': must be a string")
    if member is None:
        member = must_find("members", member_id, "Member")
    if linked is None:
        linked = must_find("award_applications", linked_id, "AwardApplication")
    rec = new_common_fields()
    rec.update({
        "member_id": member["id"],
        "linked_award_application_id": linked["id"],
        "status": "OPEN",
        "scholarship_points": None,
    })
    db.table("scholarship_apps")[rec["id"]] = rec
    return response.success(scholarship_app_view(rec), status=201)


@bp.get("/scholarship-apps")
def list_scholarship_apps():
    role, user_id = authenticate(ALL_ROLES)
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = list(db.table("scholarship_apps").values())
    linked_id = request.args.get("linked_award_application_id")
    if linked_id is not None:
        items = [s for s in items if s["linked_award_application_id"] == linked_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    items = sort_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return response.success([scholarship_app_view(s) for s in page],
                            response_type="array", pagination=meta)


@bp.get("/scholarship-apps/<sid>")
def get_scholarship_app(sid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("scholarship_apps", sid, "ScholarshipApp")
    resolve_caller(role, user_id)
    return response.success(scholarship_app_view(rec))


@bp.post("/scholarship-apps/<sid>/submit")
def submit_scholarship_app(sid):
    role, user_id = authenticate(["Member"])
    rec = must_find("scholarship_apps", sid, "ScholarshipApp")
    resolve_caller(role, user_id)
    require_member_ownership(user_id, rec["member_id"])
    # Priority 5: OPEN -> UNDER_REVIEW requires the linked award application to
    # be EVALUATED with an award_tier of GOLD or SILVER.
    if rec["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Scholarship application status must be OPEN to submit")
    linked = db.table("award_applications").get(rec["linked_award_application_id"])
    if linked is None or linked["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The linked award application must be EVALUATED")
    if linked["award_tier"] not in ("GOLD", "SILVER"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The linked award application's award_tier must be GOLD or SILVER")
    # Scholarship points: per-project values rounded half-up to integers first,
    # then summed (pinned rounding order, PRD 2.6).
    rec["scholarship_points"] = calc.scholarship_points(rec["member_id"])
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return response.success(scholarship_app_view(rec))


@bp.post("/scholarship-apps/<sid>/grant")
def grant_scholarship_app(sid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("scholarship_apps", sid, "ScholarshipApp")
    resolve_caller(role, user_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Scholarship application status must be UNDER_REVIEW to grant")
    if rec["scholarship_points"] is None or rec["scholarship_points"] < GRANT_MIN_POINTS:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Granting requires scholarship_points >= 30")
    rec["status"] = "GRANTED"
    touch(rec)
    return response.success(scholarship_app_view(rec))


@bp.post("/scholarship-apps/<sid>/decline")
def decline_scholarship_app(sid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("scholarship_apps", sid, "ScholarshipApp")
    resolve_caller(role, user_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Scholarship application status must be UNDER_REVIEW to decline")
    rec["status"] = "DECLINED"
    touch(rec)
    return response.success(scholarship_app_view(rec))
