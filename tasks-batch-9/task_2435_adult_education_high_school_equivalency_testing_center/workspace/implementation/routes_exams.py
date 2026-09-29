"""Exam sittings, candidate registrations and accommodation requests."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from core import (
    accommodation_pub,
    auth,
    body,
    by_created,
    clock,
    created,
    deny_scope,
    effective_accommodation_status,
    find_accommodation,
    find_proctor,
    find_registration,
    find_room,
    find_session,
    find_student,
    fmt_clock,
    guard_proctor_certified,
    hours_out,
    new_record,
    ok,
    opt_fk,
    opt_str,
    pagination,
    paginate,
    pub,
    q2,
    req_dt,
    req_enum,
    req_fk,
    req_int,
    req_str,
    req_str_array,
    session_center,
    store,
    touch,
)
from errors import ApiError
from routes_centers import guard_center_authorized

bp = Blueprint("exams", __name__)

MAX_SESSION_SPAN = timedelta(hours=6)
CHECK_IN_LEAD = timedelta(minutes=60)
LIVE_REGISTRATION_STATES = ("REGISTERED", "CHECKED_IN", "SCORED")


# --------------------------------------------------------------------------
# exam sessions
# --------------------------------------------------------------------------

@bp.post("/exam-sessions")
def create_session():
    role, user_id = auth("CenterAdministrator")
    data = body()
    room_id = req_fk(data, "testing_room_id")
    subtest = req_enum(data, "subtest", calc.SUBTESTS)
    starts_raw, starts_at = req_dt(data, "starts_at")
    ends_raw, ends_at = req_dt(data, "ends_at")
    requested_seats = req_int(data, "requested_seats", minimum=1)
    formats = req_str_array(data, "supported_formats", calc.FORMATS,
                            default=["STANDARD", "EXTRA_TIME"])

    room = find_room(room_id)
    if user_id != room["testing_center_id"]:
        deny_scope()
    center = store.centers.get(room["testing_center_id"])
    guard_center_authorized(center)

    if room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_OUT_OF_SERVICE")
    if subtest not in center["allowed_subtests"]:
        raise ApiError("ERR_SUBTEST_NOT_AUTHORIZED")
    if starts_at <= clock():
        raise ApiError("ERR_SESSION_IN_PAST")
    if ends_at <= starts_at or (ends_at - starts_at) > MAX_SESSION_SPAN:
        raise ApiError("ERR_INVALID_SESSION_WINDOW")
    if calc.room_occupation_conflict(room, starts_at, ends_at):
        raise ApiError("ERR_ROOM_BUFFER_CONFLICT")

    duration = q2(calc.duration_hours(starts_at, ends_at))
    session = new_record(store.sessions, {
        "testing_room_id": room["id"],
        "proctor_id": None,
        "subtest": subtest,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "requested_seats": requested_seats,
        "seat_capacity": min(requested_seats, room["seat_capacity"]),
        "seats_taken": 0,
        "duration_hours": hours_out(duration),
        "supported_formats": formats,
        "status": "DRAFT",
        "cancel_reason": None,
        "_starts_at": starts_at,
        "_ends_at": ends_at,
        "_duration_hours": duration,
    })
    return created(pub(session))


@bp.post("/exam-sessions/<session_id>/proctor-assignment")
def assign_proctor(session_id):
    role, user_id = auth("CenterAdministrator")
    session = find_session(session_id)
    center = session_center(session)
    if center is None or user_id != center["id"]:
        deny_scope()

    data = body()
    proctor_id = req_fk(data, "proctor_id")
    proctor = find_proctor(proctor_id)
    if proctor["testing_center_id"] != center["id"]:
        deny_scope()

    if session["status"] != "DRAFT":
        raise ApiError("ERR_SESSION_NOT_ASSIGNABLE")
    guard_center_authorized(center)
    guard_proctor_certified(proctor, persist=True)

    if calc.proctor_interval_conflict(proctor["id"], session["_starts_at"],
                                     session["_ends_at"], skip_session_id=session["id"]):
        raise ApiError("ERR_PROCTOR_TIME_CONFLICT")
    projected = calc.proctor_daily_projection(proctor["id"], session,
                                              skip_session_id=session["id"])
    if projected > proctor["_daily_hour_cap"]:
        raise ApiError("ERR_PROCTOR_DAILY_CAP_EXCEEDED")

    session["proctor_id"] = proctor["id"]
    session["status"] = "SCHEDULED"
    touch(session)
    proctor["assigned_session_count"] += 1
    touch(proctor)
    return ok(pub(session))


@bp.post("/exam-sessions/<session_id>/cancel")
def cancel_session(session_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority")
    session = find_session(session_id)
    if role == "CenterAdministrator":
        center = session_center(session)
        if center is None or user_id != center["id"]:
            deny_scope()
    data = body()
    reason = req_str(data, "cancel_reason")
    if session["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_SESSION_NOT_CANCELLABLE")
    cascades.cancel_session(session, reason)
    return ok(pub(session))


@bp.get("/exam-sessions/<session_id>")
def read_session(session_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority",
                         "ProgramCoordinator", "Registrar", "Proctor")
    session = find_session(session_id)
    if role == "CenterAdministrator":
        center = session_center(session)
        if center is None or user_id != center["id"]:
            deny_scope()
    if role == "Proctor" and session.get("proctor_id") != user_id:
        deny_scope()
    return ok(pub(session))


@bp.get("/exam-sessions")
def list_sessions():
    auth("CenterAdministrator", "StateAuthority", "ProgramCoordinator",
         "Registrar", "Proctor")
    limit, offset = pagination()
    rows = list(store.sessions.values())
    for key in ("testing_room_id", "proctor_id", "subtest", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# accommodation requests
# --------------------------------------------------------------------------

@bp.post("/accommodation-requests")
def create_accommodation():
    role, user_id = auth("Student", "Registrar")
    data = body()
    raw_student = data.get("student_id")
    if role == "Student" and isinstance(raw_student, str) and raw_student != user_id:
        deny_scope()
    student_id = req_fk(data, "student_id")
    requested_format = req_enum(data, "requested_format", calc.REQUESTABLE_FORMATS)
    documentation_ref = req_str(data, "documentation_ref")
    student = find_student(student_id)

    record = new_record(store.accommodations, {
        "student_id": student["id"],
        "requested_format": requested_format,
        "documentation_ref": documentation_ref,
        "status": "SUBMITTED",
        "info_request_rounds": 0,
        "granted_format": None,
        "valid_until": None,
        "decision_note": None,
        "_valid_until": None,
    })
    return created(pub(record))


@bp.post("/accommodation-requests/<request_id>/info-request")
def accommodation_info_request(request_id):
    auth("CenterAdministrator")
    record = find_accommodation(request_id)
    data = body()
    note = req_str(data, "decision_note")
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_ACCOMMODATION_NOT_PENDING")
    if record["info_request_rounds"] >= 2:
        raise ApiError("ERR_INFO_REQUEST_LIMIT_REACHED")
    record["status"] = "INFO_REQUESTED"
    record["info_request_rounds"] += 1
    record["decision_note"] = note
    touch(record)
    return ok(pub(record))


@bp.post("/accommodation-requests/<request_id>/resubmission")
def accommodation_resubmission(request_id):
    role, user_id = auth("Student", "Registrar")
    record = find_accommodation(request_id)
    if role == "Student" and user_id != record["student_id"]:
        deny_scope()
    data = body()
    documentation_ref = req_str(data, "documentation_ref")
    if record["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_ACCOMMODATION_NOT_INFO_REQUESTED")
    record["status"] = "SUBMITTED"
    record["documentation_ref"] = documentation_ref
    touch(record)
    return ok(pub(record))


@bp.post("/accommodation-requests/<request_id>/decision")
def accommodation_decision(request_id):
    auth("CenterAdministrator")
    record = find_accommodation(request_id)
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "DENY"))
    granted_format = None
    valid_raw = None
    valid_dt = None
    if decision == "APPROVE":
        granted_format = req_enum(data, "granted_format", calc.REQUESTABLE_FORMATS)
        valid_raw, valid_dt = req_dt(data, "valid_until")
    note = opt_str(data, "decision_note")

    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_ACCOMMODATION_NOT_PENDING")

    if decision == "APPROVE":
        if valid_dt <= clock():
            raise ApiError("ERR_INVALID_EFFECTIVE_WINDOW")
        record["status"] = "APPROVED"
        record["granted_format"] = granted_format
        record["valid_until"] = valid_raw
        record["_valid_until"] = valid_dt
    else:
        record["status"] = "DENIED"
    record["decision_note"] = note
    touch(record)
    return ok(pub(record))


@bp.get("/accommodation-requests/<request_id>")
def read_accommodation(request_id):
    role, user_id = auth("Registrar", "ProgramCoordinator", "StateAuthority", "Student")
    record = find_accommodation(request_id)
    if role == "Student" and user_id != record["student_id"]:
        deny_scope()
    return ok(accommodation_pub(record))


@bp.get("/accommodation-requests")
def list_accommodations():
    auth("Registrar", "ProgramCoordinator", "StateAuthority")
    limit, offset = pagination()
    rows = list(store.accommodations.values())
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [r for r in rows if r["student_id"] == student_id]
    requested_format = request.args.get("requested_format")
    if requested_format is not None:
        rows = [r for r in rows if r["requested_format"] == requested_format]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if effective_accommodation_status(r) == status]
    return paginate(by_created(rows), limit, offset, serializer=accommodation_pub)


# --------------------------------------------------------------------------
# exam registrations
# --------------------------------------------------------------------------

@bp.post("/exam-registrations")
def create_registration():
    role, user_id = auth("Registrar", "Student")
    data = body()
    raw_student = data.get("student_id")
    if role == "Student" and isinstance(raw_student, str) and raw_student != user_id:
        deny_scope()

    student_id = req_fk(data, "student_id")
    session_id = req_fk(data, "exam_session_id")
    expected = req_int(data, "expected_exam_session_version")
    accommodation_id = opt_fk(data, "accommodation_request_id")

    student = find_student(student_id)
    session = find_session(session_id)
    accommodation = (find_accommodation(accommodation_id)
                     if accommodation_id is not None else None)

    if expected != session["version"]:
        raise ApiError("ERR_STALE_EXAM_SESSION_VERSION")

    if student["intake_status"] not in ("PLACED", "ENROLLED"):
        raise ApiError("ERR_STUDENT_NOT_PLACED")

    center = session_center(session)
    guard_center_authorized(center)

    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_OPEN_FOR_REGISTRATION")
    if session["subtest"] not in center["allowed_subtests"]:
        raise ApiError("ERR_SUBTEST_NOT_AUTHORIZED")

    granted_format = None
    if accommodation is not None:
        if accommodation["student_id"] != student["id"]:
            raise ApiError("ERR_ACCOMMODATION_OWNER_MISMATCH")
        effective = effective_accommodation_status(accommodation)
        if effective == "EXPIRED":
            if accommodation["status"] == "APPROVED":
                accommodation["status"] = "EXPIRED"
                touch(accommodation)
            raise ApiError("ERR_ACCOMMODATION_EXPIRED")
        if effective != "APPROVED":
            raise ApiError("ERR_ACCOMMODATION_NOT_APPROVED")
        granted_format = accommodation["granted_format"]
        if granted_format not in session["supported_formats"]:
            raise ApiError("ERR_ACCOMMODATION_FORMAT_UNAVAILABLE")

    if session["_starts_at"] <= clock():
        raise ApiError("ERR_SESSION_IN_PAST")

    if session["seats_taken"] >= session["seat_capacity"]:
        raise ApiError("ERR_SESSION_SEATS_EXHAUSTED")

    for existing in store.registrations.values():
        if (existing["student_id"] == student["id"]
                and existing["exam_session_id"] == session["id"]
                and existing["registration_status"] in LIVE_REGISTRATION_STATES):
            raise ApiError("ERR_DUPLICATE_REGISTRATION")

    attempts = calc.prior_scored_attempts(student["id"], session["subtest"])
    fee = calc.exam_fee_assessment(
        session["subtest"], attempts, granted_format,
        student["_total_instructional_hours"], student["voucher_balance_cents"],
    )
    if not student["self_pay_authorized"] and fee["fee_due_cents"] > 0:
        raise ApiError("ERR_VOUCHER_INSUFFICIENT")

    registration = new_record(store.registrations, {
        "student_id": student["id"],
        "exam_session_id": session["id"],
        "accommodation_request_id": accommodation["id"] if accommodation else None,
        "identity_verified_by_proctor_id": None,
        "registration_status": "REGISTERED",
        "identity_status": "UNVERIFIED",
        "identity_document_type": None,
        "prior_scored_attempts": fee["prior_scored_attempts"],
        "gross_fee_cents": fee["gross_fee_cents"],
        "accommodation_surcharge_cents": fee["accommodation_surcharge_cents"],
        "discount_cents": fee["discount_cents"],
        "voucher_applied_cents": fee["voucher_applied_cents"],
        "fee_due_cents": fee["fee_due_cents"],
        "scale_score": None,
        "result_outcome": None,
        "checked_in_at": None,
        "refunded_cents": 0,
    })

    student["voucher_balance_cents"] -= fee["voucher_applied_cents"]
    student["voucher_spent_cents"] += fee["voucher_applied_cents"]
    student["exam_fee_owed_cents"] += fee["fee_due_cents"]
    touch(student)

    session["seats_taken"] += 1
    touch(session)

    return created(pub(registration))


def _registration_proctor_guard(registration, user_id):
    session = store.sessions.get(registration["exam_session_id"])
    if session is None or session.get("proctor_id") != user_id:
        deny_scope()
    return session


@bp.post("/exam-registrations/<registration_id>/identity-verification")
def identity_verification(registration_id):
    role, user_id = auth("Proctor")
    registration = find_registration(registration_id)
    _registration_proctor_guard(registration, user_id)
    proctor = store.proctors.get(user_id)
    if proctor is None:
        deny_scope()

    data = body()
    decision = req_enum(data, "decision", ("VERIFIED", "REJECTED"))
    document_type = opt_str(data, "identity_document_type")

    if registration["registration_status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_OPEN")
    if registration["identity_status"] == "VERIFIED":
        raise ApiError("ERR_IDENTITY_ALREADY_VERIFIED")

    guard_proctor_certified(proctor)

    if decision == "VERIFIED":
        registration["identity_status"] = "VERIFIED"
        registration["identity_document_type"] = document_type
        registration["identity_verified_by_proctor_id"] = proctor["id"]
    else:
        registration["identity_status"] = "ID_REJECTED"
        registration["identity_document_type"] = document_type
    touch(registration)
    return ok(pub(registration))


@bp.post("/exam-registrations/<registration_id>/check-in")
def check_in(registration_id):
    role, user_id = auth("Proctor")
    registration = find_registration(registration_id)
    session = _registration_proctor_guard(registration, user_id)
    proctor = store.proctors.get(user_id)
    if proctor is None:
        deny_scope()

    if registration["registration_status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_OPEN")

    guard_proctor_certified(proctor, persist=True)

    if registration["identity_status"] != "VERIFIED":
        raise ApiError("ERR_IDENTITY_NOT_VERIFIED")

    now = clock()
    if now < session["_starts_at"] - CHECK_IN_LEAD or now >= session["_ends_at"]:
        raise ApiError("ERR_CHECK_IN_WINDOW_CLOSED")

    first_check_in = not any(
        r["registration_status"] == "CHECKED_IN"
        for r in store.registrations.values()
        if r["exam_session_id"] == session["id"]
    )

    registration["registration_status"] = "CHECKED_IN"
    registration["checked_in_at"] = fmt_clock(now)
    touch(registration)

    if first_check_in and session["status"] == "SCHEDULED":
        session["status"] = "IN_PROGRESS"
        touch(session)

    return ok(pub(registration))


@bp.post("/exam-registrations/<registration_id>/result")
def record_result(registration_id):
    role, user_id = auth("Proctor")
    registration = find_registration(registration_id)
    session = _registration_proctor_guard(registration, user_id)
    proctor = store.proctors.get(user_id)
    if proctor is None:
        deny_scope()

    data = body()
    scale_score = req_int(data, "scale_score", minimum=100, maximum=200)

    if registration["registration_status"] != "CHECKED_IN":
        raise ApiError("ERR_REGISTRATION_NOT_CHECKED_IN")

    guard_proctor_certified(proctor)

    registration["registration_status"] = "SCORED"
    registration["scale_score"] = scale_score
    registration["result_outcome"] = (
        "PASSED" if scale_score >= calc.PASS_SCORE_PER_SUBTEST else "FAILED"
    )
    touch(registration)

    remaining = any(
        r["registration_status"] == "CHECKED_IN"
        for r in store.registrations.values()
        if r["exam_session_id"] == session["id"]
    )
    if not remaining and session["status"] == "IN_PROGRESS":
        session["status"] = "COMPLETED"
        touch(session)

    return ok(pub(registration))


@bp.post("/exam-registrations/<registration_id>/cancel")
def cancel_registration(registration_id):
    role, user_id = auth("Registrar", "Student")
    registration = find_registration(registration_id)
    if role == "Student" and user_id != registration["student_id"]:
        deny_scope()
    if registration["registration_status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_OPEN")
    session = store.sessions.get(registration["exam_session_id"])
    cascades.refund_registration(registration, session, "CANCELLED")
    if session is not None:
        touch(session)
    return ok(pub(registration))


@bp.get("/exam-registrations/<registration_id>")
def read_registration(registration_id):
    role, user_id = auth("ProgramCoordinator", "StateAuthority",
                         "CenterAdministrator", "Proctor", "Student")
    registration = find_registration(registration_id)
    if role == "Student" and user_id != registration["student_id"]:
        deny_scope()
    if role == "Proctor":
        _registration_proctor_guard(registration, user_id)
    if role == "CenterAdministrator":
        session = store.sessions.get(registration["exam_session_id"])
        center = session_center(session) if session else None
        if center is None or user_id != center["id"]:
            deny_scope()
    return ok(pub(registration))


@bp.get("/exam-registrations")
def list_registrations():
    auth("ProgramCoordinator", "StateAuthority", "CenterAdministrator",
         "Proctor", "Registrar")
    limit, offset = pagination()
    rows = list(store.registrations.values())
    for key in ("student_id", "exam_session_id", "accommodation_request_id",
                "identity_verified_by_proctor_id", "registration_status",
                "identity_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    return paginate(by_created(rows), limit, offset)
