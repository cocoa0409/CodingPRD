"""Photo routes: capture, list, get, match, approve."""
from flask import Blueprint, request

import db
import store
from common import (
    get_body,
    paginate,
    parse_pagination,
    require_fields,
    require_str,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response
from services.matching import best_match

bp = Blueprint("photos", __name__)

ALL_OPERATORS = ["SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk"]


@bp.route("/api/photos", methods=["POST"])
def create_photo():
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    body = get_body()
    require_fields(body, ["picture_day_session_id", "candidate_name", "candidate_grade", "candidate_homeroom"])
    sid = require_str(body, "picture_day_session_id")
    candidate_name = require_str(body, "candidate_name")
    candidate_grade = require_str(body, "candidate_grade")
    candidate_homeroom = require_str(body, "candidate_homeroom")

    with db.LOCK:
        store.get_session(sid)
        row = store.new_row("photo", {
            "picture_day_session_id": sid,
            "matched_student_id": None,
            "retake_of_photo_id": None,
            "candidate_grade": candidate_grade,
            "candidate_homeroom": candidate_homeroom,
            "candidate_name": candidate_name,
            "match_confidence_score": 0,
            "yearbook_exported": False,
            "status": "UNMATCHED",
        })
        db.photos[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/photos", methods=["GET"])
def list_photos():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    matched_student_id = request.args.get("matched_student_id")
    retake_of_photo_id = request.args.get("retake_of_photo_id")
    status = request.args.get("status")
    rows = list(db.photos.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    if matched_student_id is not None:
        rows = [r for r in rows if r["matched_student_id"] == matched_student_id]
    if retake_of_photo_id is not None:
        rows = [r for r in rows if r["retake_of_photo_id"] == retake_of_photo_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/photos/<rid>", methods=["GET"])
def get_photo(rid):
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS + ["Guardian"])
    return object_response(store.serialize(store.get_photo(rid)))


@bp.route("/api/photos/<rid>/match", methods=["POST"])
def match_photo(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        photo = store.get_photo(rid)
        session = store.get_session(photo["picture_day_session_id"])
        if session["status"] != "CAPTURE_OPEN":
            raise err("ERR_SESSION_NOT_CAPTURING", "Session is not capturing")
        # Photo must be UNMATCHED to enter MATCHED.
        if photo["status"] != "UNMATCHED":
            raise err("ERR_NO_MATCH_CANDIDATE", "Photo is not in a matchable state")
        winner, score = best_match(photo)
        photo["matched_student_id"] = winner["id"]
        photo["match_confidence_score"] = score
        photo["status"] = "MATCHED"
        store.touch(photo)
        # Matched student ENROLLED -> PHOTOGRAPHED.
        winner["status"] = "PHOTOGRAPHED"
        store.touch(winner)
    return object_response(store.serialize(photo))


@bp.route("/api/photos/<rid>/approve", methods=["POST"])
def approve_photo(rid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    with db.LOCK:
        photo = store.get_photo(rid)
        session = store.get_session(photo["picture_day_session_id"])
        if session["status"] != "GALLERY_OPEN":
            raise err("ERR_SESSION_NOT_GALLERY", "Session is not in gallery")
        if photo["status"] not in ("MATCHED", "RETAKEN"):
            raise err("ERR_PHOTO_NOT_APPROVABLE", "Photo is not approvable")
        photo["status"] = "APPROVED"
        store.touch(photo)
    return object_response(store.serialize(photo))
