"""Award applications and star nominations (PRD 3.9; club-version OCC per 2.7)."""

from flask import Blueprint, request

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_common_fields, touch)
from validation import (get_body, as_enum, as_int, as_int_range, as_num_range,
                        pagination_params, paginate, sort_by_creation, present)
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_SEGREGATION_OF_DUTIES,
                    ERR_STAR_QUOTA_EXCEEDED)
from services import calc
from services.serialize import award_application_view

bp = Blueprint("award_applications", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]
AWARD_TRACKS = ("DEGREE", "STAR", "SCHOLARSHIP")
STAR_QUOTA = 2


@bp.post("/award-applications")
def create_award_application():
    role, user_id = authenticate(["Member"])
    body = get_body()
    # Priority 3: referenced identifiers exist, left-to-right (member_id, record_book_id).
    member = None
    book = None
    if isinstance(body.get("member_id"), str):
        member = must_find("members", body["member_id"], "Member")
    if isinstance(body.get("record_book_id"), str):
        book = must_find("record_books", body["record_book_id"], "RecordBook")
    resolve_caller(role, user_id)
    # Priority 4: a member drafts their own award application.
    if isinstance(body.get("member_id"), str):
        require_member_ownership(user_id, body["member_id"])
    # Priority 14: request shape.
    member_id = present(body, "member_id")
    if not isinstance(member_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'member_id': must be a string")
    record_book_id = present(body, "record_book_id")
    if not isinstance(record_book_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'record_book_id': must be a string")
    if member is None:
        member = must_find("members", member_id, "Member")
    if book is None:
        book = must_find("record_books", record_book_id, "RecordBook")
    award_track = as_enum(body, "award_track", AWARD_TRACKS)
    rec = new_common_fields()
    rec.update({
        "member_id": member["id"],
        "award_track": award_track,
        "record_book_id": book["id"],
        "status": "DRAFT",
        "rubric_score": None,
        "award_tier": None,
        "nominated_by": None,
    })
    db.table("award_applications")[rec["id"]] = rec
    return response.success(award_application_view(rec), status=201)


@bp.get("/award-applications")
def list_award_applications():
    role, user_id = authenticate(ALL_ROLES)
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = list(db.table("award_applications").values())
    record_book_id = request.args.get("record_book_id")
    if record_book_id is not None:
        items = [a for a in items if a["record_book_id"] == record_book_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    items = sort_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return response.success([award_application_view(a) for a in page],
                            response_type="array", pagination=meta)


@bp.get("/award-applications/<aid>")
def get_award_application(aid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    return response.success(award_application_view(rec))


def _club_of_application(app):
    member = db.table("members").get(app["member_id"])
    if member is None:
        return None
    return db.table("clubs").get(member["club_id"])


@bp.post("/award-applications/<aid>/nominate")
def nominate_award_application(aid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    # Priority 5: DRAFT -> NOMINATED, and the linked record book must be APPROVED.
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Award application status must be DRAFT to nominate")
    book = db.table("record_books").get(rec["record_book_id"])
    if book is None or book["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Nomination requires the linked record book to be APPROVED")
    club = _club_of_application(rec)
    # Priority 10: STAR quota -- two active star nominations per club is the
    # hard ceiling.
    if rec["award_track"] == "STAR" and club is not None:
        if club["star_nomination_count"] >= STAR_QUOTA:
            raise ApiError(ERR_STAR_QUOTA_EXCEEDED, 422,
                           "Club already has 2 active STAR nominations")
    # Priority 14: request shape -- the OCC field is a non-optional input (2.7).
    body = get_body()
    expected_club_version = as_int(body, "expected_club_version")
    # Priority 15: optimistic concurrency on the nominee member's club --
    # always the final gate.
    if club is None or expected_club_version != club["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_club_version does not match the club's current version")
    rec["status"] = "NOMINATED"
    rec["nominated_by"] = user_id
    touch(rec)
    if rec["award_track"] == "STAR" and club is not None:
        club["star_nomination_count"] += 1
        touch(club)
    return response.success(award_application_view(rec))


@bp.post("/award-applications/<aid>/endorse")
def endorse_award_application(aid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    if rec["status"] != "NOMINATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Award application status must be NOMINATED to endorse")
    # Priority 6: segregation of duties -- endorsement must be performed by a
    # different volunteer than the one recorded in nominated_by.
    if rec["nominated_by"] == user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The endorsing volunteer must differ from the nominating volunteer")
    rec["status"] = "ENDORSED"
    touch(rec)
    return response.success(award_application_view(rec))


@bp.post("/award-applications/<aid>/evaluate")
def evaluate_award_application(aid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    if rec["status"] != "ENDORSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Award application status must be ENDORSED to evaluate")
    # Priority 14: participation_pct (0-100) and leadership_pts (>= 0 integer).
    body = get_body()
    participation_pct = as_num_range(body, "participation_pct", lo=0, hi=100)
    leadership_pts = as_int_range(body, "leadership_pts", lo=0)
    book = db.table("record_books").get(rec["record_book_id"])
    final_score = book["final_score"] if book is not None else None
    if final_score is None:
        # Unreachable through the declared transitions (nomination required an
        # APPROVED book, which carries a final_score and is terminal).
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The linked record book has no final score")
    score, tier = calc.award_rubric_score(final_score, participation_pct, leadership_pts)
    rec["rubric_score"] = float(score)
    rec["award_tier"] = tier
    rec["status"] = "EVALUATED"
    touch(rec)
    return response.success(award_application_view(rec))


@bp.post("/award-applications/<aid>/award")
def award_award_application(aid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    if rec["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Award application status must be EVALUATED to award")
    if rec["award_tier"] == "NONE" or rec["award_tier"] is None:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Awarding requires an award_tier other than NONE")
    rec["status"] = "AWARDED"
    touch(rec)
    # For the STAR track awarding releases the club's star slot.
    if rec["award_track"] == "STAR":
        club = _club_of_application(rec)
        if club is not None:
            club["star_nomination_count"] -= 1
            touch(club)
    return response.success(award_application_view(rec))


@bp.post("/award-applications/<aid>/deny")
def deny_award_application(aid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    if rec["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Award application status must be EVALUATED to deny")
    if rec["award_tier"] != "NONE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Denying requires an award_tier of exactly NONE")
    rec["status"] = "DENIED"
    touch(rec)
    return response.success(award_application_view(rec))


@bp.post("/award-applications/<aid>/withdraw")
def withdraw_award_application(aid):
    role, user_id = authenticate(["Member"])
    rec = must_find("award_applications", aid, "AwardApplication")
    resolve_caller(role, user_id)
    require_member_ownership(user_id, rec["member_id"])
    # A member may withdraw their own application from NOMINATED or ENDORSED.
    if rec["status"] not in ("NOMINATED", "ENDORSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Award application status must be NOMINATED or ENDORSED to withdraw")
    was_nominated = rec["status"] == "NOMINATED"
    rec["status"] = "WITHDRAWN"
    touch(rec)
    # Withdrawing a NOMINATED STAR application releases the club's star slot;
    # withdrawing an ENDORSED application simply retires the application.
    if was_nominated and rec["award_track"] == "STAR":
        club = _club_of_application(rec)
        if club is not None:
            club["star_nomination_count"] -= 1
            touch(club)
    return response.success(award_application_view(rec))
