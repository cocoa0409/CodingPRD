"""TestSession routes (create, get, list, close)."""
from flask import Blueprint, request

from db import store, stamp_create, touch
from errors import (err, ERR_INVALID_REQUEST, ERR_SESSION_WINDOW_OVERLAP)
from middleware import require_roles
from response import object_response, array_response
from services import lookups, serializers
from services.common import (get_json_body, require_fields, require_enum,
                             parse_iso_dt, parse_test_date_start_utc,
                             parse_pagination, paginate, sort_by_created_at)
from services import engine

bp = Blueprint("sessions", __name__)

EXAM_TYPES = {"SAT", "ACT", "AP"}


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


@bp.route("/test-sessions", methods=["POST"])
@require_roles("TestCenterAdmin")
def create_session():
    body = get_json_body()
    require_fields(body, ["test_center_id", "exam_type", "exam_subject",
                          "test_date", "window_start_utc", "window_end_utc",
                          "base_fee_cents"])

    # Existence (FK) before well-formedness of business rules.
    center = lookups.test_center(body["test_center_id"])

    exam_type = require_enum(body["exam_type"], EXAM_TYPES, "exam_type")
    exam_subject = body["exam_subject"]
    if not isinstance(exam_subject, str):
        raise err(ERR_INVALID_REQUEST, "exam_subject must be a string")

    base_fee = body["base_fee_cents"]
    if not isinstance(base_fee, int) or isinstance(base_fee, bool) or base_fee < 0:
        raise err(ERR_INVALID_REQUEST, "base_fee_cents must be a non-negative integer")

    test_date_str = body["test_date"]
    # Validate parseable date / datetimes.
    parse_test_date_start_utc(test_date_str)
    window_start = parse_iso_dt(body["window_start_utc"])
    window_end = parse_iso_dt(body["window_end_utc"])

    # Window-overlap check: same center, same test_date, half-open windows.
    for other in store.test_sessions.values():
        if other["test_center_id"] != center["id"]:
            continue
        if other["test_date"] != test_date_str:
            continue
        o_start = parse_iso_dt(other["window_start_utc"])
        o_end = parse_iso_dt(other["window_end_utc"])
        if _windows_overlap(window_start, window_end, o_start, o_end):
            raise err(ERR_SESSION_WINDOW_OVERLAP,
                      "Session window overlaps an existing session at this center on this date")

    session = {
        "test_center_id": center["id"],
        "exam_type": exam_type,
        "exam_subject": exam_subject,
        "test_date": test_date_str,
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "base_fee_cents": base_fee,
        "standard_seats_reserved": 0,
        "accommodated_seats_reserved": 0,
        "registration_status": "OPEN",
    }
    stamp_create(session)  # version=1
    store.test_sessions[session["id"]] = session
    return object_response(serializers.test_session(session), 201)


@bp.route("/test-sessions/<sid>", methods=["GET"])
@require_roles("TestCenterAdmin", "Candidate", "ScoreOps", "AccommodationReviewer")
def get_session(sid):
    session = lookups.test_session(sid)
    return object_response(serializers.test_session(session), 200)


@bp.route("/test-sessions", methods=["GET"])
@require_roles("TestCenterAdmin", "Candidate", "ScoreOps", "AccommodationReviewer")
def list_sessions():
    limit, offset = parse_pagination()
    test_center_id = request.args.get("test_center_id")
    exam_type = request.args.get("exam_type")

    items = list(store.test_sessions.values())
    if test_center_id is not None:
        items = [s for s in items if s["test_center_id"] == test_center_id]
    if exam_type is not None:
        items = [s for s in items if s["exam_type"] == exam_type]

    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.test_session(s) for s in page],
                          limit, offset, total, 200)


@bp.route("/test-sessions/<sid>/close", methods=["POST"])
@require_roles("TestCenterAdmin")
def close_session(sid):
    session = lookups.test_session(sid)

    # registration_status -> CLOSED
    session["registration_status"] = "CLOSED"
    touch(session)

    # Sweep registrations: CONFIRMED never-CHECKED_IN -> NO_SHOW (release seat,
    # no refund, version bump per release). A CHECKED_IN reg that never received
    # a score is likewise a no-show (no seat release described for that path —
    # it was already counted, but it is terminal; treat per PRD: swept to NO_SHOW).
    regs = [r for r in store.registrations.values()
            if r["test_session_id"] == session["id"]]
    for reg in regs:
        if reg["lifecycle_status"] == "CONFIRMED":
            reg["lifecycle_status"] = "NO_SHOW"
            touch(reg)
            # Release matching seat pool (no refund).
            if reg["seat_kind"] == "STANDARD":
                engine.remove_standard_seat(session)
            else:
                engine.remove_accommodated_seat(session)
        elif reg["lifecycle_status"] == "CHECKED_IN":
            # Checked in but never scored -> considered a no-show at close.
            # Per the state machine (CHECKED_IN->NO_SHOW side_effects: []) no
            # seat release happens for this path; only the status flips.
            if reg["score_status"] == "PENDING":
                reg["lifecycle_status"] = "NO_SHOW"
                touch(reg)

    # Expire WAITING standby entries.
    for e in store.standby_entries.values():
        if e["test_session_id"] == session["id"] and e["status"] == "WAITING":
            e["status"] = "EXPIRED"
            touch(e)

    return object_response(serializers.test_session(session), 200)
