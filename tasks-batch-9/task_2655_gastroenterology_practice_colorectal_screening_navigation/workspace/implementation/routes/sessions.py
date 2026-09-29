"""Room blocks (EndoscopySession) and anesthesia coverage."""
from flask import Blueprint

from core import by_seq, db, fail, iso, new_record, parse_instant, touch
from core import respond_list, respond_object
from calcs import anesthesia_load, session_capacity_minutes
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_enum,
    opt_int,
    opt_string,
    pagination,
    req_date,
    req_enum,
    req_id,
    req_instant,
    req_string,
)
from services import get_clinician, get_coverage, get_session

bp = Blueprint("sessions", __name__)

SESSION_STATUSES = ("DRAFT", "PUBLISHED", "COVERAGE_CONFIRMED", "SUSPENDED", "CLOSED")
LIVE_BOOKING_STATUSES = ("BOOKED", "CHECKED_IN", "IN_PROGRESS")


def _active_full_coverage(session_id, exclude_id=None):
    for row in db.coverages.values():
        if row["session_id"] != session_id or row["status"] != "ACTIVE":
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["covers_full_window"]:
            return row
    return None


# ---- create / read / list ------------------------------------------------
@bp.post("/endoscopy-sessions")
def create_session():
    auth("PracticeAdmin")
    data = body()
    room_code = req_string(data, "room_code")
    session_date = req_date(data, "session_date")
    req_instant(data, "window_start_utc")
    req_instant(data, "window_end_utc")
    lead_endoscopist_id = req_id(data, "lead_endoscopist_id")
    anesthesia_mode = opt_enum(
        data, "anesthesia_mode", ("MODERATE_SEDATION", "MAC"), "MODERATE_SEDATION"
    )
    turnover_minutes = opt_int(data, "turnover_minutes", 0, 60, 15)
    max_procedures = opt_int(data, "max_procedures", 1, 20, 8)

    lead = get_clinician(lead_endoscopist_id)
    if lead["clinician_type"] != "ENDOSCOPIST":
        fail("ERR_CLINICIAN_TYPE_MISMATCH", "A room block must be led by an ENDOSCOPIST.")

    session = new_record({
        "room_code": room_code,
        "session_date": session_date,
        "window_start_utc": data["window_start_utc"],
        "window_end_utc": data["window_end_utc"],
        "lead_endoscopist_id": lead_endoscopist_id,
        "anesthesia_mode": anesthesia_mode,
        "turnover_minutes": turnover_minutes,
        "max_procedures": max_procedures,
        "capacity_minutes": 0,
        "booked_minutes": 0,
        "remaining_minutes": 0,
        "status": "DRAFT",
        "suspension_reason": None,
    })
    capacity = session_capacity_minutes(session)
    session["capacity_minutes"] = capacity
    session["remaining_minutes"] = capacity
    db.sessions[session["id"]] = session
    return respond_object(session, 201)


@bp.get("/endoscopy-sessions/<session_id>")
def read_session(session_id):
    auth("PracticeAdmin", "ReferralCoordinator", "Endoscopist")
    return respond_object(get_session(session_id))


@bp.get("/endoscopy-sessions")
def list_sessions():
    auth("PracticeAdmin", "ReferralCoordinator", "Endoscopist")
    limit, offset = pagination()
    lead_endoscopist_id = filter_value("lead_endoscopist_id")
    session_date = filter_value("session_date")
    status = filter_enum("status", SESSION_STATUSES)
    rows = by_seq(list(db.sessions.values()))
    if lead_endoscopist_id is not None:
        rows = [r for r in rows if r["lead_endoscopist_id"] == lead_endoscopist_id]
    if session_date is not None:
        rows = [r for r in rows if r["session_date"] == session_date]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


# ---- posture actions -----------------------------------------------------
@bp.post("/endoscopy-sessions/<session_id>/status-actions")
def session_status_action(session_id):
    auth("PracticeAdmin")
    data = body()
    action = req_enum(data, "action", ("PUBLISH", "SUSPEND", "RESUME", "CLOSE"))
    reason = opt_string(data, "reason")
    if action == "SUSPEND" and reason is None:
        fail("ERR_INVALID_REQUEST", "SUSPEND requires a reason.")

    session = get_session(session_id)
    status = session["status"]

    if action == "PUBLISH":
        if status != "DRAFT":
            fail("ERR_INVALID_SESSION_STATE", "PUBLISH is not admitted from %s." % status)
        session["capacity_minutes"] = session_capacity_minutes(session)
        session["status"] = "PUBLISHED"
        session["remaining_minutes"] = session["capacity_minutes"]
    elif action == "SUSPEND":
        if status not in ("PUBLISHED", "COVERAGE_CONFIRMED"):
            fail("ERR_INVALID_SESSION_STATE", "SUSPEND is not admitted from %s." % status)
        session["status"] = "SUSPENDED"
        session["suspension_reason"] = reason
    elif action == "RESUME":
        if status != "SUSPENDED":
            fail("ERR_INVALID_SESSION_STATE", "RESUME is not admitted from %s." % status)
        session["suspension_reason"] = None
        session["status"] = (
            "COVERAGE_CONFIRMED" if _active_full_coverage(session["id"]) else "PUBLISHED"
        )
    else:
        if status not in ("PUBLISHED", "COVERAGE_CONFIRMED", "SUSPENDED"):
            fail("ERR_INVALID_SESSION_STATE", "CLOSE is not admitted from %s." % status)
        for booking in db.bookings.values():
            if booking["session_id"] == session["id"] and \
                    booking["status"] in LIVE_BOOKING_STATUSES:
                fail("ERR_INVALID_SESSION_STATE",
                     "The block still holds a booking in %s." % booking["status"])
        session["status"] = "CLOSED"
        for row in db.coverages.values():
            if row["session_id"] == session["id"] and row["status"] == "ACTIVE":
                row["status"] = "RELEASED"
                touch(row)
    touch(session)
    return respond_object(session)


# ---- anesthesia coverage -------------------------------------------------
@bp.post("/endoscopy-sessions/<session_id>/anesthesia-coverage")
def create_coverage(session_id):
    auth("PracticeAdmin")
    data = body()
    anesthesia_clinician_id = req_id(data, "anesthesia_clinician_id")
    start = req_instant(data, "coverage_start_utc")
    end = req_instant(data, "coverage_end_utc")

    session = get_session(session_id)
    clinician = get_clinician(anesthesia_clinician_id)

    if session["status"] != "PUBLISHED":
        fail("ERR_INVALID_SESSION_STATE",
             "Coverage may only be assigned to a PUBLISHED block, not %s." % session["status"])
    if clinician["clinician_type"] != "ANESTHESIA":
        fail("ERR_CLINICIAN_TYPE_MISMATCH", "Coverage requires an ANESTHESIA clinician.")

    peak, overlap_index = anesthesia_load(anesthesia_clinician_id, start, end)
    if peak > clinician["max_overlapping_rooms"]:
        fail("ERR_ANESTHESIA_CONCURRENCY_EXCEEDED",
             "Peak concurrent coverage %d exceeds the ceiling of %d."
             % (peak, clinician["max_overlapping_rooms"]))

    window_start = parse_instant(session["window_start_utc"])
    window_end = parse_instant(session["window_end_utc"])
    covers_full_window = start <= window_start and end >= window_end
    if not covers_full_window:
        fail("ERR_COVERAGE_WINDOW_INSUFFICIENT", "Coverage must fully span the block window.")

    coverage = new_record({
        "session_id": session["id"],
        "anesthesia_clinician_id": anesthesia_clinician_id,
        "coverage_start_utc": data["coverage_start_utc"],
        "coverage_end_utc": data["coverage_end_utc"],
        "covers_full_window": covers_full_window,
        "overlap_index": overlap_index,
        "status": "ACTIVE",
    })
    db.coverages[coverage["id"]] = coverage
    if session["status"] == "PUBLISHED" and covers_full_window:
        session["status"] = "COVERAGE_CONFIRMED"
    touch(session)
    return respond_object(coverage, 201)


@bp.get("/anesthesia-coverage/<coverage_id>")
def read_coverage(coverage_id):
    auth("PracticeAdmin", "Endoscopist")
    return respond_object(get_coverage(coverage_id))


@bp.get("/anesthesia-coverage")
def list_coverage():
    auth("PracticeAdmin", "Endoscopist")
    limit, offset = pagination()
    session_id = filter_value("session_id")
    clinician_id = filter_value("anesthesia_clinician_id")
    status = filter_enum("status", ("ACTIVE", "RELEASED"))
    rows = by_seq(list(db.coverages.values()))
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if clinician_id is not None:
        rows = [r for r in rows if r["anesthesia_clinician_id"] == clinician_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.delete("/anesthesia-coverage/<coverage_id>")
def release_coverage(coverage_id):
    auth("PracticeAdmin")
    coverage = get_coverage(coverage_id)
    session = db.sessions.get(coverage["session_id"])
    if coverage["status"] != "ACTIVE":
        fail("ERR_INVALID_SESSION_STATE", "Only an ACTIVE coverage row may be released.")
    if session is None or session["status"] not in ("COVERAGE_CONFIRMED", "SUSPENDED"):
        fail("ERR_INVALID_SESSION_STATE",
             "The block's status does not admit releasing coverage.")

    coverage["status"] = "RELEASED"
    touch(coverage)
    if session["status"] == "COVERAGE_CONFIRMED" and \
            _active_full_coverage(session["id"]) is None:
        session["status"] = "PUBLISHED"
    touch(session)
    return respond_object(coverage)
