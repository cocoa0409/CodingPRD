"""AccommodationRequest routes: submit, get, list, and the review machine
(begin-review, request-info, resubmit, approve, deny).
"""
from flask import Blueprint, request

from db import store, stamp_create, touch
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_504_IEP_ELIGIBLE, ERR_ACCOMMODATION_NOT_BINDABLE,
                    ERR_CANDIDATE_SCHEDULE_CONFLICT, ERR_ACCOMMODATED_FULL)
from middleware import require_roles
from response import object_response, array_response
from services import lookups, serializers
from services.common import (get_json_body, require_fields, require_enum,
                             parse_pagination, paginate, sort_by_created_at,
                             parse_iso_dt)
from services import calculations as calc
from services import engine

bp = Blueprint("accommodations", __name__)

ACCOMMODATION_TYPES = {"EXTENDED_TIME_50", "EXTENDED_TIME_100", "SEPARATE_ROOM", "BREAKS_ONLY"}
BASES = {"PLAN_504", "IEP"}


@bp.route("/accommodation-requests", methods=["POST"])
@require_roles("Candidate")
def create_accommodation():
    body = get_json_body()
    require_fields(body, ["candidate_id", "target_registration_id",
                          "accommodation_type", "basis"])

    # Existence: candidate then target registration (left-to-right).
    candidate = lookups.candidate(body["candidate_id"])
    target_reg = lookups.registration(body["target_registration_id"])

    accommodation_type = require_enum(body["accommodation_type"],
                                      ACCOMMODATION_TYPES, "accommodation_type")
    basis = require_enum(body["basis"], BASES, "basis")

    acc = {
        "candidate_id": candidate["id"],
        "target_registration_id": target_reg["id"],
        "accommodation_type": accommodation_type,
        "basis": basis,
        "reviewer_note": None,
        "status": "SUBMITTED",
    }
    stamp_create(acc)
    store.accommodation_requests[acc["id"]] = acc
    return object_response(serializers.accommodation_request(acc), 201)


@bp.route("/accommodation-requests/<aid>", methods=["GET"])
@require_roles("Candidate", "AccommodationReviewer", "TestCenterAdmin")
def get_accommodation(aid):
    acc = lookups.accommodation_request(aid)
    return object_response(serializers.accommodation_request(acc), 200)


@bp.route("/accommodation-requests", methods=["GET"])
@require_roles("Candidate", "AccommodationReviewer", "TestCenterAdmin")
def list_accommodations():
    limit, offset = parse_pagination()
    candidate_id = request.args.get("candidate_id")
    target_registration_id = request.args.get("target_registration_id")
    status = request.args.get("status")

    items = list(store.accommodation_requests.values())
    if candidate_id is not None:
        items = [a for a in items if a["candidate_id"] == candidate_id]
    if target_registration_id is not None:
        items = [a for a in items if a["target_registration_id"] == target_registration_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]

    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.accommodation_request(a) for a in page],
                          limit, offset, total, 200)


@bp.route("/accommodation-requests/<aid>/begin-review", methods=["POST"])
@require_roles("AccommodationReviewer")
def begin_review(aid):
    acc = lookups.accommodation_request(aid)
    if acc["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Accommodation request is not SUBMITTED")
    candidate = lookups.candidate(acc["candidate_id"])
    if not candidate.get("has_active_504_iep"):
        raise err(ERR_NOT_504_IEP_ELIGIBLE,
                  "Candidate has no active 504/IEP on file")
    acc["status"] = "UNDER_REVIEW"
    touch(acc)
    return object_response(serializers.accommodation_request(acc), 200)


@bp.route("/accommodation-requests/<aid>/request-info", methods=["POST"])
@require_roles("AccommodationReviewer")
def request_info(aid):
    acc = lookups.accommodation_request(aid)
    body = get_json_body()
    require_fields(body, ["reviewer_note"])
    if not isinstance(body["reviewer_note"], str):
        raise err(ERR_INVALID_REQUEST, "reviewer_note must be a string")
    if acc["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Accommodation request is not UNDER_REVIEW")
    acc["status"] = "MORE_INFO_NEEDED"
    acc["reviewer_note"] = body["reviewer_note"]
    touch(acc)
    return object_response(serializers.accommodation_request(acc), 200)


@bp.route("/accommodation-requests/<aid>/resubmit", methods=["POST"])
@require_roles("Candidate")
def resubmit(aid):
    acc = lookups.accommodation_request(aid)
    if acc["status"] != "MORE_INFO_NEEDED":
        raise err(ERR_INVALID_STATE, "Accommodation request is not MORE_INFO_NEEDED")
    acc["status"] = "UNDER_REVIEW"
    touch(acc)
    return object_response(serializers.accommodation_request(acc), 200)


@bp.route("/accommodation-requests/<aid>/deny", methods=["POST"])
@require_roles("AccommodationReviewer")
def deny(aid):
    acc = lookups.accommodation_request(aid)
    body = get_json_body()
    require_fields(body, ["reviewer_note"])
    if not isinstance(body["reviewer_note"], str):
        raise err(ERR_INVALID_REQUEST, "reviewer_note must be a string")
    if acc["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Accommodation request is not UNDER_REVIEW")
    acc["status"] = "DENIED"
    acc["reviewer_note"] = body["reviewer_note"]
    touch(acc)
    return object_response(serializers.accommodation_request(acc), 200)


@bp.route("/accommodation-requests/<aid>/approve", methods=["POST"])
@require_roles("AccommodationReviewer")
def approve(aid):
    acc = lookups.accommodation_request(aid)

    # State validity (priority 6).
    if acc["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Accommodation request is not UNDER_REVIEW")

    target_reg = lookups.registration(acc["target_registration_id"])
    session = lookups.test_session(target_reg["test_session_id"])
    center = lookups.test_center(session["test_center_id"])

    # Bindability (priority 9): target not yet CHECKED_IN, lifecycle RESERVED/CONFIRMED,
    # owned by the requesting candidate.
    if target_reg["lifecycle_status"] not in ("RESERVED", "CONFIRMED"):
        raise err(ERR_ACCOMMODATION_NOT_BINDABLE,
                  "Target registration is not bindable")
    if target_reg["candidate_id"] != acc["candidate_id"]:
        raise err(ERR_ACCOMMODATION_NOT_BINDABLE,
                  "Target registration belongs to a different candidate")

    # Candidate schedule separation (priority 11) — ahead of capacity check.
    _check_rest_separation(acc["candidate_id"], session, exclude_reg_id=target_reg["id"])

    # Accommodated-pool capacity (priority 14).
    if session["accommodated_seats_reserved"] >= center["room_capacity_accommodated"]:
        raise err(ERR_ACCOMMODATED_FULL, "Accommodated pool is full")

    # ----- Atomic settlement -----
    acc["status"] = "APPROVED"
    touch(acc)

    target_reg["accommodation_request_id"] = acc["id"]
    target_reg["seat_kind"] = "ACCOMMODATED"
    # Depth-2 cascade: recompute allotted_minutes from approved multiplier.
    target_reg["allotted_minutes"] = calc.allotted_minutes(
        session["exam_type"], acc["accommodation_type"])
    touch(target_reg)

    # Move seat between pools (standard -1, accommodated +1) + version bump.
    session["standard_seats_reserved"] -= 1
    session["accommodated_seats_reserved"] += 1
    engine.bump_session_version(session)

    return object_response(serializers.accommodation_request(acc), 200)


def _check_rest_separation(candidate_id, new_session, exclude_reg_id):
    """A candidate's two ACCOMMODATED sittings must keep a >=3h rest gap between
    the earlier window_end_utc and the later window_start_utc. Gap < 3h
    (incl. overlap / back-to-back) -> ERR_CANDIDATE_SCHEDULE_CONFLICT.

    new_session is the session the freshly-accommodated sitting belongs to.
    """
    new_start = parse_iso_dt(new_session["window_start_utc"])
    new_end = parse_iso_dt(new_session["window_end_utc"])

    # Find the candidate's other ACCOMMODATED registrations (active lifecycle),
    # excluding the one being approved now.
    for reg in store.registrations.values():
        if reg["id"] == exclude_reg_id:
            continue
        if reg["candidate_id"] != candidate_id:
            continue
        if reg["seat_kind"] != "ACCOMMODATED":
            continue
        if reg["lifecycle_status"] not in ("RESERVED", "CONFIRMED", "CHECKED_IN"):
            continue
        other_session = store.test_sessions.get(reg["test_session_id"])
        if other_session is None:
            continue
        o_start = parse_iso_dt(other_session["window_start_utc"])
        o_end = parse_iso_dt(other_session["window_end_utc"])

        # Order the two sittings in time; required gap = later.start - earlier.end.
        if new_start >= o_start:
            earlier_end, later_start = o_end, new_start
        else:
            earlier_end, later_start = new_end, o_start
        gap_seconds = (later_start - earlier_end).total_seconds()
        if gap_seconds < calc.REST_BUFFER_HOURS * 3600:
            raise err(ERR_CANDIDATE_SCHEDULE_CONFLICT,
                      "Accommodated sittings violate the rest-buffer separation")
