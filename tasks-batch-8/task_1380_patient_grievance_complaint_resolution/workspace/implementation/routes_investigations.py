"""Routes: investigations, investigation notes, interview bookings."""

from datetime import timedelta

from flask import Blueprint, g, request

import db
import derived
import errors
import middleware
from clock import iso_ms, parse_iso
from helpers import (
    NOTE_TYPES,
    check_bool,
    check_datetime,
    check_enum,
    check_string,
    get_body,
    paginate,
    parse_pagination,
    require_present,
    serialize_booking,
    serialize_investigation,
    serialize_note,
    sorted_by_creation,
    stamp_light,
    stamp_new,
    touch,
)
from response import success_list, success_object
from routes_cases import get_case_or_404
from state import CLOCK

bp = Blueprint("investigations", __name__)

BUFFER_SECONDS = 900


def get_investigation_or_404(investigation_id):
    investigation = db.investigations.get(investigation_id)
    if investigation is None:
        raise errors.not_found(
            errors.ERR_INVESTIGATION_NOT_FOUND, "Investigation not found"
        )
    return investigation


# ---------------------------------------------------------------------------
# Investigation
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases/<case_id>/investigations", methods=["POST"])
def create_investigation(case_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    get_body()
    case = get_case_or_404(case_id)
    if case["lifecycle_status"] != "ASSIGNED":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Investigation requires the case ASSIGNED"
        )
    if derived.active_primary_assignment(case["id"]) is None:
        raise errors.api_error(
            errors.ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT,
            409,
            "Investigation open requires an ACTIVE PRIMARY CaseAssignment on the case",
        )
    investigation = stamp_new()
    investigation.update(
        {
            "case_id": case["id"],
            "status": "OPEN",
            "care_concern_flag": False,
            "findings_summary": None,
            "submitted_by_id": None,
            "submitted_at": None,
        }
    )
    db.investigations[investigation["id"]] = investigation
    case["lifecycle_status"] = "UNDER_INVESTIGATION"
    touch(case)
    return success_object(serialize_investigation(investigation), 201)


@bp.route("/api/investigations", methods=["GET"])
def list_investigations():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    investigations = list(db.investigations.values())
    if case_id is not None:
        investigations = [i for i in investigations if i["case_id"] == case_id]
    if status is not None:
        investigations = [i for i in investigations if i["status"] == status]
    investigations = sorted_by_creation(investigations)
    page, total = paginate(investigations, limit, offset)
    return success_list(
        [serialize_investigation(i) for i in page], limit, offset, total
    )


@bp.route("/api/investigations/<investigation_id>", methods=["GET"])
def get_investigation(investigation_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    investigation = get_investigation_or_404(investigation_id)
    return success_object(serialize_investigation(investigation))


@bp.route("/api/investigations/<investigation_id>/notes", methods=["POST"])
def create_note(investigation_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    body = get_body()
    require_present(body, "note_type", "body")
    investigation = get_investigation_or_404(investigation_id)
    note_type = check_enum(body, "note_type", NOTE_TYPES, required=True)
    text = check_string(body, "body", required=True)
    note = stamp_light()
    note.update(
        {
            "investigation_id": investigation["id"],
            "author_id": g.user_id,
            "note_type": note_type,
            "body": text,
        }
    )
    db.investigation_notes[note["id"]] = note
    return success_object(serialize_note(note), 201)


@bp.route("/api/investigation-notes", methods=["GET"])
def list_notes():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    investigation_id = request.args.get("investigation_id")
    note_type = request.args.get("note_type")
    notes = list(db.investigation_notes.values())
    if investigation_id is not None:
        notes = [n for n in notes if n["investigation_id"] == investigation_id]
    if note_type is not None:
        notes = [n for n in notes if n["note_type"] == note_type]
    notes = sorted_by_creation(notes)
    page, total = paginate(notes, limit, offset)
    return success_list([serialize_note(n) for n in page], limit, offset, total)


@bp.route("/api/investigation-notes/<note_id>", methods=["GET"])
def get_note(note_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    note = db.investigation_notes.get(note_id)
    if note is None:
        raise errors.not_found(errors.ERR_NOTE_NOT_FOUND, "InvestigationNote not found")
    return success_object(serialize_note(note))


@bp.route("/api/investigations/<investigation_id>/submit-findings", methods=["POST"])
def submit_findings(investigation_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    body = get_body()
    require_present(body, "findings_summary")
    investigation = get_investigation_or_404(investigation_id)
    if investigation["status"] != "OPEN":
        raise errors.api_error(
            errors.ERR_INVESTIGATION_INVALID_STATE, 409, "Investigation is not OPEN"
        )
    note_count, interview_count = derived.investigation_note_counts(investigation["id"])
    if note_count < 2 or interview_count < 1:
        raise errors.api_error(
            errors.ERR_INSUFFICIENT_INVESTIGATION_EVIDENCE,
            409,
            "submit-findings requires >= 2 notes total and >= 1 INTERVIEW note",
        )
    findings_summary = check_string(body, "findings_summary", required=True)
    care_concern_flag = check_bool(body, "care_concern_flag", default=False)
    now = CLOCK.now()
    investigation["status"] = "FINDINGS_SUBMITTED"
    investigation["findings_summary"] = findings_summary
    investigation["care_concern_flag"] = care_concern_flag
    investigation["submitted_by_id"] = g.user_id
    investigation["submitted_at"] = iso_ms(now)
    touch(investigation)
    case = get_case_or_404(investigation["case_id"])
    if case["lifecycle_status"] == "UNDER_INVESTIGATION":
        case["lifecycle_status"] = "FINDINGS_REVIEW"
        touch(case)
    return success_object(serialize_investigation(investigation))


@bp.route("/api/investigations/<investigation_id>/return-findings", methods=["POST"])
def return_findings(investigation_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    body = get_body()
    require_present(body, "return_reason")
    investigation = get_investigation_or_404(investigation_id)
    if investigation["status"] != "FINDINGS_SUBMITTED":
        raise errors.api_error(
            errors.ERR_INVESTIGATION_INVALID_STATE,
            409,
            "Investigation is not FINDINGS_SUBMITTED",
        )
    check_string(body, "return_reason", required=True)
    investigation["status"] = "OPEN"
    investigation["findings_summary"] = None
    investigation["submitted_by_id"] = None
    touch(investigation)
    case = get_case_or_404(investigation["case_id"])
    if case["lifecycle_status"] == "FINDINGS_REVIEW":
        case["lifecycle_status"] = "UNDER_INVESTIGATION"
        touch(case)
    return success_object(serialize_investigation(investigation))


@bp.route("/api/investigations/<investigation_id>/accept-findings", methods=["POST"])
def accept_findings(investigation_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    get_body()
    investigation = get_investigation_or_404(investigation_id)
    if investigation["status"] != "FINDINGS_SUBMITTED":
        raise errors.api_error(
            errors.ERR_INVESTIGATION_INVALID_STATE,
            409,
            "Investigation is not FINDINGS_SUBMITTED",
        )
    investigation["status"] = "FINDINGS_ACCEPTED"
    touch(investigation)
    case = get_case_or_404(investigation["case_id"])
    if case["lifecycle_status"] == "FINDINGS_REVIEW":
        case["lifecycle_status"] = "RESPONSE_DRAFTING"
        touch(case)
    # Cascade link: a submitted care_concern_flag auto-files a CARE_CONCERN
    # escalation with filed_by_id taken from the findings submitter.
    if investigation["care_concern_flag"]:
        escalation = stamp_new()
        escalation.update(
            {
                "case_id": case["id"],
                "escalation_type": "CARE_CONCERN",
                "source": "AUTO_CARE_FLAG",
                "status": "FILED",
                "review_track": None,
                "compliance_review_done": False,
                "safety_review_done": False,
                "filed_by_id": investigation["submitted_by_id"],
                "adjudicated_by_id": None,
                "adjudicated_at": None,
                "outcome_note": None,
            }
        )
        db.escalations[escalation["id"]] = escalation
    return success_object(serialize_investigation(investigation))


@bp.route("/api/investigations/<investigation_id>/resume", methods=["POST"])
def resume_investigation(investigation_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    get_body()
    investigation = get_investigation_or_404(investigation_id)
    if investigation["status"] != "REOPENED":
        raise errors.api_error(
            errors.ERR_INVESTIGATION_INVALID_STATE, 409, "Investigation is not REOPENED"
        )
    case = get_case_or_404(investigation["case_id"])
    if case["lifecycle_status"] != "REOPENED":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Case is not REOPENED"
        )
    investigation["status"] = "OPEN"
    touch(investigation)
    case["lifecycle_status"] = "UNDER_INVESTIGATION"
    touch(case)
    return success_object(serialize_investigation(investigation))


# ---------------------------------------------------------------------------
# InterviewBooking
# ---------------------------------------------------------------------------


@bp.route("/api/interview-bookings", methods=["POST"])
def create_booking():
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    body = get_body()
    require_present(body, "investigation_id", "room_id", "start_at", "end_at")
    investigation = db.investigations.get(body.get("investigation_id"))
    if investigation is None:
        raise errors.not_found(
            errors.ERR_INVESTIGATION_NOT_FOUND, "Investigation not found"
        )
    room = db.interview_rooms.get(body.get("room_id"))
    if room is None:
        raise errors.not_found(errors.ERR_ROOM_NOT_FOUND, "InterviewRoom not found")
    # Identity binding (rung 5): caller must be the case's ACTIVE PRIMARY
    # investigator.
    primary = derived.active_primary_assignment(investigation["case_id"])
    if primary is None or primary["investigator_id"] != g.user_id:
        raise errors.identity_mismatch(
            "Caller is not the case's ACTIVE PRIMARY investigator"
        )
    # Cross-aggregate (rung 9): inactive rooms reject new bookings.
    if not room["active"]:
        raise errors.api_error(errors.ERR_ROOM_INACTIVE, 409, "InterviewRoom is inactive")
    start_dt = check_datetime(body, "start_at", required=True)
    end_dt = check_datetime(body, "end_at", required=True)
    # Occupancy (rung 10): 900-second buffer on both sides against every other
    # BOOKED booking on the same room; a gap of exactly 900s is allowed.
    buffer = timedelta(seconds=BUFFER_SECONDS)
    for other in db.interview_bookings.values():
        if other["room_id"] != room["id"] or other["status"] != "BOOKED":
            continue
        other_start = parse_iso(other["start_at"])
        other_end = parse_iso(other["end_at"])
        if not (end_dt <= other_start - buffer or start_dt >= other_end + buffer):
            raise errors.api_error(
                errors.ERR_BOOKING_BUFFER_VIOLATION,
                409,
                "Room booking lacks the required 900-second buffer",
            )
    # Temporal sanity (rung 11).
    now = CLOCK.now()
    if end_dt <= start_dt or start_dt < now:
        raise errors.api_error(
            errors.ERR_BOOKING_WINDOW_INVALID,
            422,
            "Booking window end_at <= start_at or start_at before now",
        )
    booking = stamp_new()
    booking.update(
        {
            "investigation_id": investigation["id"],
            "room_id": room["id"],
            "start_at": iso_ms(start_dt),
            "end_at": iso_ms(end_dt),
            "status": "BOOKED",
            "booked_by_id": g.user_id,
        }
    )
    db.interview_bookings[booking["id"]] = booking
    return success_object(serialize_booking(booking), 201)


@bp.route("/api/interview-bookings", methods=["GET"])
def list_bookings():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    investigation_id = request.args.get("investigation_id")
    room_id = request.args.get("room_id")
    status = request.args.get("status")
    bookings = list(db.interview_bookings.values())
    if investigation_id is not None:
        bookings = [b for b in bookings if b["investigation_id"] == investigation_id]
    if room_id is not None:
        bookings = [b for b in bookings if b["room_id"] == room_id]
    if status is not None:
        bookings = [b for b in bookings if b["status"] == status]
    bookings = sorted_by_creation(bookings)
    page, total = paginate(bookings, limit, offset)
    return success_list([serialize_booking(b) for b in page], limit, offset, total)


@bp.route("/api/interview-bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    booking = db.interview_bookings.get(booking_id)
    if booking is None:
        raise errors.not_found(errors.ERR_BOOKING_NOT_FOUND, "InterviewBooking not found")
    return success_object(serialize_booking(booking))


@bp.route("/api/interview-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    get_body()
    booking = db.interview_bookings.get(booking_id)
    if booking is None:
        raise errors.not_found(errors.ERR_BOOKING_NOT_FOUND, "InterviewBooking not found")
    if booking["booked_by_id"] != g.user_id:
        raise errors.identity_mismatch("Caller is not the booking investigator")
    if booking["status"] != "BOOKED":
        raise errors.api_error(
            errors.ERR_BOOKING_INVALID_STATE, 409, "Booking is not BOOKED"
        )
    booking["status"] = "CANCELLED"
    touch(booking)
    return success_object(serialize_booking(booking))
