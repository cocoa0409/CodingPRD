"""Session routes — book, list, get, confirm, cancel, complete."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import clock, parse_iso
from config import MAX_SESSION_MINUTES, MIN_LEAD_MINUTES
from db import db, init_common_fields, touch
from errors import APIError
from middleware import require_auth
from response import list_response, success_response
from services.pagination import get_pagination, slice_items
from services.pricing import (
    compute_commission_cents,
    compute_gross_cents,
    scheduled_minutes_of,
)
from services.sessions import (
    cancel_session_by_student,
    cancel_session_by_tutor,
    complete_session,
    sessions_overlap,
)
from services.validators import (
    optional_int,
    require_body,
    require_bool,
    require_field,
    require_string,
    require_subject_code,
)

session_bp = Blueprint("session", __name__)


def _resolve_active_link(parent_id, student_id):
    for link in db.parent_child_links.values():
        if (
            link["parent_id"] == parent_id
            and link["student_id"] == student_id
            and link["link_status"] == "ACTIVE"
        ):
            return link
    return None


def _session_accessible_by(session, user_id, user_role):
    if user_role == "PlatformAdmin":
        return True
    if user_role == "PlatformArbiter":
        return True
    if user_role == "Tutor" and user_id == session["tutor_id"]:
        return True
    if user_role == "Student" and user_id == session["student_id"]:
        return True
    if user_role == "Parent":
        student = db.students.get(session["student_id"])
        if student is None or student["account_type"] != "MINOR":
            return False
        return _resolve_active_link(user_id, student["id"]) is not None
    return False


@session_bp.route("/sessions", methods=["POST"])
@require_auth({"Student", "Parent"})
def book_session():
    body = request.get_json(silent=True) or {}
    require_body(body)

    tutor_id = require_string(body, "tutor_id")
    student_id = require_string(body, "student_id")
    subject_code = require_subject_code(body, "subject_code")
    start_at_raw = require_string(body, "start_at")
    end_at_raw = require_string(body, "end_at")
    is_trial = require_bool(body, "is_trial", default=False)
    apply_credits = require_bool(body, "apply_credits", default=False)

    # FK existence
    tutor = db.tutors.get(tutor_id)
    student = db.students.get(student_id)
    if tutor is None or student is None:
        raise APIError("ERR_NOT_FOUND")

    # Auth: caller must be the student (ADULT) or linked parent (MINOR)
    if g.user_role == "Student":
        if g.user_id != student_id:
            raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
        if student["account_type"] == "MINOR":
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
    else:  # Parent
        if student["account_type"] != "MINOR":
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
        link = _resolve_active_link(g.user_id, student_id)
        if link is None:
            raise APIError("ERR_MINOR_REQUIRES_PARENT")

    # Subject offered check
    approved = any(
        t["tutor_id"] == tutor_id and t["subject_code"] == subject_code and t["status"] == "APPROVED"
        for t in db.subject_tags.values()
    )
    if not approved:
        raise APIError("ERR_SUBJECT_NOT_OFFERED")

    # Tutor verified
    if tutor["verification_status"] != "VERIFIED":
        raise APIError("ERR_TUTOR_NOT_VERIFIED")

    # Window
    start_at = parse_iso(start_at_raw)
    end_at = parse_iso(end_at_raw)
    if end_at <= start_at:
        raise APIError("ERR_INVALID_SESSION_WINDOW")
    duration_seconds = (end_at - start_at).total_seconds()
    if duration_seconds <= 0:
        raise APIError("ERR_INVALID_SESSION_WINDOW")
    # Duration must be whole-minute and <= MAX_SESSION_MINUTES
    if duration_seconds % 60 != 0:
        raise APIError("ERR_INVALID_SESSION_WINDOW")
    minutes = int(duration_seconds / 60)
    if minutes <= 0 or minutes > MAX_SESSION_MINUTES:
        raise APIError("ERR_INVALID_SESSION_WINDOW")
    now = clock.now()
    if start_at < now + timedelta(minutes=MIN_LEAD_MINUTES):
        raise APIError("ERR_INVALID_SESSION_WINDOW")

    # Trial uniqueness
    if is_trial:
        for s in db.sessions.values():
            if s["tutor_id"] == tutor_id and s["student_id"] == student_id:
                if s.get("is_trial"):
                    raise APIError("ERR_TRIAL_ALREADY_USED")
                if s["status"] == "COMPLETED" or s["status"] == "SETTLED":
                    raise APIError("ERR_TRIAL_ALREADY_USED")

    # Pricing
    gross_cents, scheduled_minutes = compute_gross_cents(tutor, start_at, end_at, is_trial)

    # Credits
    credit_applied = 0
    if apply_credits and not is_trial:
        available = student.get("credit_balance_cents", 0)
        credit_applied = min(gross_cents, available)
        if credit_applied < 0:
            raise APIError("ERR_CREDIT_APPLY_INVALID")
    elif apply_credits and is_trial:
        # Trial bookings ignore the flag; pinned to 0
        credit_applied = 0
    charged = gross_cents - credit_applied
    if charged < 0:
        raise APIError("ERR_CREDIT_APPLY_INVALID")

    # Provisional commission on charged amount at booking tier
    provisional = compute_commission_cents(
        charged, tutor.get("lifetime_completed_sessions", 0)
    )

    session = init_common_fields({
        "tutor_id": tutor_id,
        "student_id": student_id,
        "subject_code": subject_code,
        "start_at": start_at_raw,
        "end_at": end_at_raw,
        "is_trial": is_trial,
        "apply_credits": apply_credits,
        "status": "REQUESTED",
        "gross_price_cents": gross_cents,
        "credit_applied_cents": credit_applied,
        "charged_amount_cents": charged,
        "provisional_commission_cents": provisional,
        "final_commission_cents": 0,
        "actual_gross_cents": 0,
        "arbitration_refund_cents": 0,
        "tutor_payout_cents": 0,
        "adjusted_minutes": None,
        "cancellation_fee_cents": 0,
        "refund_to_student_cents": 0,
    })

    # Deduct credit from student
    if credit_applied > 0:
        student["credit_balance_cents"] = student.get("credit_balance_cents", 0) - credit_applied
        touch(student)

    db.sessions[session["id"]] = session
    return success_response(session, status=201)


@session_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth({"Tutor", "Student", "Parent", "PlatformAdmin", "PlatformArbiter"})
def get_session(session_id):
    session = db.sessions.get(session_id)
    if session is None:
        raise APIError("ERR_NOT_FOUND")
    if not _session_accessible_by(session, g.user_id, g.user_role):
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    return success_response(session, status=200)


@session_bp.route("/sessions", methods=["GET"])
@require_auth({"Tutor", "Student", "Parent", "PlatformAdmin"})
def list_sessions():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    from_dt = parse_iso(from_raw) if from_raw else None
    to_dt = parse_iso(to_raw) if to_raw else None

    items = []
    for s in db.sessions.values():
        if not _session_accessible_by(s, g.user_id, g.user_role):
            continue
        if status_filter and s["status"] != status_filter:
            continue
        start = parse_iso(s["start_at"])
        if from_dt and start < from_dt:
            continue
        if to_dt and start > to_dt:
            continue
        items.append(s)
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = slice_items(items, limit, offset)
    return list_response(page, total, limit, offset, status=200)


@session_bp.route("/sessions/<session_id>/confirm", methods=["POST"])
@require_auth({"Tutor"})
def confirm_session(session_id):
    session = db.sessions.get(session_id)
    if session is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_id != session["tutor_id"]:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if session["status"] != "REQUESTED":
        raise APIError("ERR_INVALID_STATE")
    tutor = db.tutors[session["tutor_id"]]
    if tutor["verification_status"] != "VERIFIED":
        raise APIError("ERR_TUTOR_NOT_VERIFIED")
    # Overlap check
    for other in db.sessions.values():
        if other["id"] == session["id"]:
            continue
        if other["tutor_id"] != session["tutor_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        if sessions_overlap(session, other):
            raise APIError("ERR_SESSION_OVERLAP")
    session["status"] = "CONFIRMED"
    touch(session)
    return success_response(session, status=200)


@session_bp.route("/sessions/<session_id>/cancel", methods=["POST"])
@require_auth({"Student", "Parent", "Tutor"})
def cancel_session(session_id):
    session = db.sessions.get(session_id)
    if session is None:
        raise APIError("ERR_NOT_FOUND")
    if session["status"] not in ("REQUESTED", "CONFIRMED"):
        raise APIError("ERR_INVALID_STATE")

    if g.user_role == "Student":
        if g.user_id != session["student_id"]:
            raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
        student = db.students[session["student_id"]]
        if student["account_type"] == "MINOR":
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
        cancel_session_by_student(session, by_tutor_or_system=False)
    elif g.user_role == "Parent":
        student = db.students[session["student_id"]]
        if student["account_type"] != "MINOR":
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
        link = _resolve_active_link(g.user_id, session["student_id"])
        if link is None:
            raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
        cancel_session_by_student(session, by_tutor_or_system=False)
    else:  # Tutor
        if g.user_id != session["tutor_id"]:
            raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
        cancel_session_by_tutor(session)

    return success_response(session, status=200)


@session_bp.route("/sessions/<session_id>/complete", methods=["POST"])
@require_auth({"Tutor"})
def complete_session_endpoint(session_id):
    session = db.sessions.get(session_id)
    if session is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_id != session["tutor_id"]:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if session["status"] != "IN_PROGRESS":
        raise APIError("ERR_INVALID_STATE")

    body = request.get_json(silent=True) or {}
    adjusted = optional_int(body, "adjusted_minutes", min_value=None, max_value=None)
    scheduled = scheduled_minutes_of(parse_iso(session["start_at"]), parse_iso(session["end_at"]))
    if adjusted is not None:
        if adjusted < 0 or adjusted > scheduled:
            raise APIError("ERR_ADJUSTED_MINUTES_OUT_OF_RANGE")
    # The "10-minute early wrap" rule
    now = clock.now()
    end_at = parse_iso(session["end_at"])
    effective_adjusted = adjusted if adjusted is not None else scheduled
    if now < end_at and effective_adjusted < scheduled - 10:
        # Can't complete early without sufficient adjusted_minutes
        raise APIError("ERR_INVALID_STATE")

    complete_session(session, adjusted)
    return success_response(session, status=200)
