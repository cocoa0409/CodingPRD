"""Programs, program enrollments (fee subsidy), workshop sessions and
workshop enrollments (seat allocation + waitlist promotion)."""
from datetime import timedelta
from flask import Blueprint, request

import db
import services
from auth import require, get_or_404
from calc import latest_verified_screening, compute_fee_subsidy
from envelope import ok, ok_list, paginate
from errors import ApiError, bad_request, invalid_state
from util import (body_json, req_str, req_int, req_enum, req_present,
                  req_datetime)

bp = Blueprint("programs", __name__)

PROGRAM_KINDS = {"ESOL", "WORKFORCE"}
ENROLLMENT_STATUSES = {"APPLIED", "ELIGIBLE", "ENROLLED", "COMPLETED",
                       "WITHDRAWN", "DENIED"}
LIVE_PROGRAM_ENROLLMENT = ("APPLIED", "ELIGIBLE", "ENROLLED")
LIVE_WORKSHOP_ENROLLMENT = ("ENROLLED", "WAITLISTED")

ROOM_BUFFER = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.route("/programs", methods=["POST"])
def create_program():
    require("CenterAdmin")
    data = body_json()
    name = req_str(data, "name")
    kind = req_enum(data, "kind", PROGRAM_KINDS)
    capacity = req_int(data, "capacity", minimum=1)
    base_fee = req_int(data, "base_fee_cents", minimum=0)
    completion = req_int(data, "cost_per_completion_cents", minimum=0)
    program = db.new_entity("programs", {
        "name": name,
        "kind": kind,
        "capacity": capacity,
        "base_fee_cents": base_fee,
        "cost_per_completion_cents": completion,
        "enrolled_count": 0,
        "status": "OPEN",
    })
    return ok(db.pub(program), status=201)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    program = get_or_404("programs", program_id, "program")
    return ok(db.pub(program))


@bp.route("/programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    require("CenterAdmin")
    program = get_or_404("programs", program_id, "program")
    if program["status"] not in ("OPEN", "FULL"):
        raise invalid_state("program is not OPEN or FULL")
    program["status"] = "CLOSED"
    db.touch(program)
    # teach-out: APPLIED/ELIGIBLE denied; ENROLLED unaffected
    for enr in db.all_of("enrollments"):
        if (enr["program_id"] == program_id
                and enr["status"] in ("APPLIED", "ELIGIBLE")):
            enr["status"] = "DENIED"
            enr["denial_reason"] = "PROGRAM_CLOSED"
            db.touch(enr)
    return ok(db.pub(program))


# ---------------------------------------------------------------------------
# Program enrollments
# ---------------------------------------------------------------------------

@bp.route("/program-enrollments", methods=["POST"])
def create_enrollment():
    require("CaseManager", "IntakeSpecialist")
    data = body_json()

    # rung 3: fixed id order — case_id before program_id
    case_id = data.get("case_id")
    program_id = data.get("program_id")
    case = program = None
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")
    if program_id is not None:
        if not isinstance(program_id, str):
            raise bad_request("program_id must be a string")
        program = get_or_404("programs", program_id, "program")

    # rung 4: SUSPENDED/CLOSED cases reject new child-service writes
    if case is not None and case["service_status"] in ("SUSPENDED", "CLOSED"):
        raise invalid_state("case is not accepting new enrollments")

    # rung 7: structural incl. duplicate live enrollment
    req_present(data, "case_id")
    req_present(data, "program_id")
    if any(e for e in db.all_of("enrollments")
           if e["program_id"] == program_id and e["case_id"] == case_id
           and e["status"] in LIVE_PROGRAM_ENROLLMENT):
        raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409,
                       "a live enrollment already exists for this pair")

    # rung 9: cross-entity state
    if case["service_status"] != "ACTIVE":
        raise ApiError("ERR_CASE_NOT_ACTIVE", 409,
                       "case must be ACTIVE to apply")
    if program["status"] == "CLOSED":
        raise ApiError("ERR_PROGRAM_CLOSED", 409, "program is CLOSED")

    enr = db.new_entity("enrollments", {
        "case_id": case_id,
        "program_id": program_id,
        "status": "APPLIED",
        "subsidy_pct": None,
        "subsidized_fee_cents": None,
        "fee_status": "PENDING",
        "denial_reason": None,
        "completed_at": None,
    })
    return ok(db.pub(enr), status=201)


@bp.route("/program-enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    enr = get_or_404("enrollments", enrollment_id, "program enrollment")
    return ok(db.pub(enr))


@bp.route("/program-enrollments", methods=["GET"])
def list_enrollments():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("enrollments")
    for param in ("case_id", "program_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if str(e.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(e) for e in page], meta)


@bp.route("/program-enrollments/<enrollment_id>/transition",
          methods=["POST"])
def transition_enrollment(enrollment_id):
    require("CaseManager", "CenterAdmin")
    enr = get_or_404("enrollments", enrollment_id, "program enrollment")
    data = body_json()
    to_status = data.get("to_status")
    if not isinstance(to_status, str) or to_status not in ENROLLMENT_STATUSES:
        raise bad_request("to_status must be a valid enrollment status")

    frm = enr["status"]
    program = db.get("programs", enr["program_id"])

    if (frm, to_status) == ("APPLIED", "ELIGIBLE"):
        if program["base_fee_cents"] > 0:
            screening = latest_verified_screening(enr["case_id"])
            if screening is None:
                raise ApiError(
                    "ERR_SUBSIDY_UNVERIFIED", 409,
                    "a VERIFIED-variant screening is required for "
                    "fee-bearing programs")
            pct, final_fee = compute_fee_subsidy(program, screening)
            enr["subsidy_pct"] = pct
            enr["subsidized_fee_cents"] = final_fee
        else:
            enr["subsidy_pct"] = None
            enr["subsidized_fee_cents"] = 0
        enr["fee_status"] = ("WAIVED" if enr["subsidized_fee_cents"] == 0
                             else "PENDING")
    elif (frm, to_status) == ("ELIGIBLE", "ENROLLED"):
        if program["status"] == "CLOSED":
            raise ApiError("ERR_PROGRAM_CLOSED", 409, "program is CLOSED")
        if enr["fee_status"] not in ("ARRANGED", "WAIVED"):
            raise ApiError("ERR_FEE_NOT_ARRANGED", 409,
                           "fee must be ARRANGED or WAIVED")
        if program["enrolled_count"] >= program["capacity"]:
            raise ApiError("ERR_PROGRAM_FULL", 409, "program is full")
        program["enrolled_count"] += 1
        services.program_sync_signage(program)
        db.touch(program)
    elif (frm, to_status) in (("APPLIED", "DENIED"), ("ELIGIBLE", "DENIED")):
        reason = data.get("denial_reason")
        if reason is not None and not isinstance(reason, str):
            raise bad_request("denial_reason must be a string")
        enr["denial_reason"] = reason
    elif (frm, to_status) == ("ENROLLED", "WITHDRAWN"):
        program["enrolled_count"] -= 1
        services.program_sync_signage(program)
        db.touch(program)
    elif (frm, to_status) == ("ENROLLED", "COMPLETED"):
        enr["completed_at"] = db.now()
        program["enrolled_count"] -= 1
        services.program_sync_signage(program)
        db.touch(program)
    else:
        raise invalid_state(
            f"cannot transition enrollment {frm} -> {to_status}")

    enr["status"] = to_status
    db.touch(enr)
    return ok(db.pub(enr))


@bp.route("/program-enrollments/<enrollment_id>/arrange-fee",
          methods=["POST"])
def arrange_fee(enrollment_id):
    require("CaseManager")
    enr = get_or_404("enrollments", enrollment_id, "program enrollment")
    if enr["status"] != "ELIGIBLE" or enr["fee_status"] != "PENDING":
        raise invalid_state("no PENDING fee to arrange")
    enr["fee_status"] = "ARRANGED"
    db.touch(enr)
    return ok(db.pub(enr))


# ---------------------------------------------------------------------------
# Workshop sessions
# ---------------------------------------------------------------------------

def _room_conflict(room_id, starts_at, ends_at):
    """Buffered CLOSED interval intersection among SCHEDULED/HELD sessions."""
    new_lo, new_hi = starts_at - ROOM_BUFFER, ends_at + ROOM_BUFFER
    for sess in db.all_of("sessions"):
        if sess["room_id"] != room_id:
            continue
        if sess["status"] not in ("SCHEDULED", "HELD"):
            continue
        ex_lo = sess["starts_at"] - ROOM_BUFFER
        ex_hi = sess["ends_at"] + ROOM_BUFFER
        if new_lo <= ex_hi and ex_lo <= new_hi:
            return True
    return False


@bp.route("/workshop-sessions", methods=["POST"])
def create_session():
    require("CaseManager", "CenterAdmin")
    data = body_json()

    room_id = data.get("room_id")
    if room_id is not None:
        if not isinstance(room_id, str):
            raise bad_request("room_id must be a string")
        get_or_404("rooms", room_id, "room")

    req_present(data, "room_id")
    title = req_str(data, "title")
    capacity = req_int(data, "capacity", minimum=1)
    starts_at = req_datetime(data, "starts_at")
    ends_at = req_datetime(data, "ends_at")
    if ends_at <= starts_at:
        raise bad_request("ends_at must be after starts_at")

    if starts_at < db.now():
        raise ApiError("ERR_TIME_IN_PAST", 409,
                       "starts_at precedes the current logical clock")
    if _room_conflict(room_id, starts_at, ends_at):
        raise ApiError("ERR_ROOM_TIME_CONFLICT", 409,
                       "room has a conflicting session within the buffer")

    sess = db.new_entity("sessions", {
        "room_id": room_id,
        "title": title,
        "capacity": capacity,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "enrolled_count": 0,
        "waitlist_count": 0,
        "open_seats": capacity,
        "_next_waitlist_pos": 1,
    })
    return ok(db.pub(sess), status=201)


@bp.route("/workshop-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    sess = get_or_404("sessions", session_id, "workshop session")
    return ok(db.pub(sess))


@bp.route("/workshop-sessions", methods=["GET"])
def list_sessions():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("sessions")
    for param in ("room_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if str(s.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(s) for s in page], meta)


@bp.route("/workshop-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    require("CaseManager", "CenterAdmin")
    sess = get_or_404("sessions", session_id, "workshop session")
    if sess["status"] != "SCHEDULED":
        raise invalid_state("session is not SCHEDULED")
    sess["status"] = "CANCELLED"
    for w in db.all_of("wk_enrollments"):
        if (w["session_id"] == session_id
                and w["status"] in LIVE_WORKSHOP_ENROLLMENT):
            w["status"] = "CANCELLED"
            db.touch(w)
    sess["enrolled_count"] = 0
    sess["waitlist_count"] = 0
    sess["open_seats"] = sess["capacity"]
    db.touch(sess)
    return ok(db.pub(sess))


# ---------------------------------------------------------------------------
# Workshop enrollments
# ---------------------------------------------------------------------------

@bp.route("/workshop-enrollments", methods=["POST"])
def create_wk_enrollment():
    require("CaseManager", "IntakeSpecialist")
    data = body_json()

    # rung 3: fixed id order — case_id before session_id
    case_id = data.get("case_id")
    session_id = data.get("session_id")
    case = sess = None
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")
    if session_id is not None:
        if not isinstance(session_id, str):
            raise bad_request("session_id must be a string")
        sess = get_or_404("sessions", session_id, "workshop session")

    # rung 4: state gates
    if case is not None and case["service_status"] in ("SUSPENDED", "CLOSED"):
        raise invalid_state("case is not accepting new enrollments")
    if sess is not None and sess["status"] != "SCHEDULED":
        raise invalid_state("session is not SCHEDULED")

    # rung 7: structural incl. duplicate live enrollment
    req_present(data, "case_id")
    req_present(data, "session_id")
    if any(w for w in db.all_of("wk_enrollments")
           if w["session_id"] == session_id and w["case_id"] == case_id
           and w["status"] in LIVE_WORKSHOP_ENROLLMENT):
        raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409,
                       "a live enrollment already exists for this pair")

    # workshop_seat_allocation
    if sess["enrolled_count"] >= sess["capacity"]:
        status = "WAITLISTED"
        position = sess["_next_waitlist_pos"]
        sess["_next_waitlist_pos"] += 1
    else:
        status = "ENROLLED"
        position = None

    enr = db.new_entity("wk_enrollments", {
        "session_id": session_id,
        "case_id": case_id,
        "status": status,
        "waitlist_position": position,
        "attended_marked_at": None,
    })
    services.session_recount(sess)
    db.touch(sess)
    return ok(db.pub(enr), status=201)


@bp.route("/workshop-enrollments/<wk_enrollment_id>", methods=["GET"])
def get_wk_enrollment(wk_enrollment_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    enr = get_or_404("wk_enrollments", wk_enrollment_id,
                     "workshop enrollment")
    return ok(db.pub(enr))


@bp.route("/workshop-enrollments", methods=["GET"])
def list_wk_enrollments():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("wk_enrollments")
    for param in ("session_id", "case_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if str(w.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(w) for w in page], meta)


@bp.route("/workshop-enrollments/<wk_enrollment_id>/cancel",
          methods=["POST"])
def cancel_wk_enrollment(wk_enrollment_id):
    require("CaseManager", "CenterAdmin")
    enr = get_or_404("wk_enrollments", wk_enrollment_id,
                     "workshop enrollment")
    if enr["status"] not in LIVE_WORKSHOP_ENROLLMENT:
        raise invalid_state("enrollment cannot be cancelled")
    sess = db.get("sessions", enr["session_id"])
    was_enrolled = enr["status"] == "ENROLLED"
    enr["status"] = "CANCELLED"
    db.touch(enr)

    if was_enrolled and sess is not None:
        # promote the waitlist head (lowest waitlist_position), if any
        waitlisted = [w for w in db.all_of("wk_enrollments")
                      if w["session_id"] == sess["id"]
                      and w["status"] == "WAITLISTED"]
        if waitlisted:
            head = min(waitlisted, key=lambda w: w["waitlist_position"])
            head["status"] = "ENROLLED"
            db.touch(head)
    if sess is not None:
        services.session_recount(sess)
        db.touch(sess)
    return ok(db.pub(enr))


@bp.route("/workshop-enrollments/<wk_enrollment_id>/mark-attendance",
          methods=["POST"])
def mark_attendance(wk_enrollment_id):
    require("CaseManager")
    enr = get_or_404("wk_enrollments", wk_enrollment_id,
                     "workshop enrollment")
    sess = db.get("sessions", enr["session_id"])
    if sess is None or sess["status"] != "HELD":
        raise invalid_state("session is not HELD")
    if enr["status"] != "ENROLLED":
        raise invalid_state("enrollment is not ENROLLED")
    data = body_json()
    attended = data.get("attended")
    if not isinstance(attended, bool):
        raise bad_request("attended must be a boolean")
    if attended:
        enr["status"] = "ATTENDED"
        enr["attended_marked_at"] = db.now()
    else:
        enr["status"] = "NO_SHOW"
    db.touch(enr)
    # seat released after the fact
    services.session_recount(sess)
    db.touch(sess)
    return ok(db.pub(enr))
