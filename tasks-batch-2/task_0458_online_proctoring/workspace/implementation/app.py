"""Online Proctoring & Remote Exam API — entry point + all routes.

Storage is in-memory only (db.py). No entity is ever seeded; the store starts
empty on every boot. Every endpoint, field, and side effect traces to a PRD
sentence (references inline).
"""
import os

from flask import Flask, request

import db
import errors
import helpers
import services
from clock import parse_iso, set_logical_now, get_logical_now
from errors import ApiError
from helpers import public_view
from middleware import authenticate, require_roles
from response import success, list_success, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Roles (PRD §2.1)
SC = "SchedulingCoordinator"
PR = "Proctor"
RO = "ReviewOfficer"
CA = "Candidate"

MONITORING_MODES = {"LIVE", "RECORD_REVIEW"}
FLAG_KINDS = {"LOCKDOWN_BREACH", "GAZE_OFF_SCREEN", "SECOND_FACE", "PROHIBITED_MATERIAL", "NETWORK_DROP"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
VERDICTS = {"UPHELD", "DISMISSED"}

SESSION_TERMINAL = {"COMPLETED", "VOIDED"}


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(err):
    # Method not allowed on a known path -> treat as forbidden routing; respond
    # with a not-found style error envelope to keep the contract JSON.
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response(errors.ERR_VALIDATION, f"Unexpected error: {err}", 422)


# ===========================================================================
# Lookup helpers (left-to-right existence; PRD §2.5)
# ===========================================================================
def find_or_404(collection, key):
    rec = collection.get(key)
    if rec is None:
        raise errors.not_found()
    return rec


def fk_or_404(collection, key):
    """Foreign-key existence check; missing -> ERR_NOT_FOUND (priority 3)."""
    if key is None:
        return None
    rec = collection.get(key)
    if rec is None:
        raise errors.not_found()
    return rec


# ===========================================================================
# Institution
# ===========================================================================
@app.route("/institutions", methods=["POST"])
def create_institution():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    name = helpers.require_str(body, "name")
    threshold = helpers.optional_int(body, "report_threshold_score", default=70,
                                     minimum=0, maximum=100)
    rec = {
        "id": db.new_id(),
        "name": name,
        "report_threshold_score": threshold,
    }
    db.stamp_create(rec, versioned=True)
    db.institutions[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/institutions/<institution_id>", methods=["GET"])
def get_institution(institution_id):
    _, role = authenticate()
    require_roles(role, [SC, RO])
    rec = find_or_404(db.institutions, institution_id)
    return success(public_view(rec), status=200, response_type="object")


# ===========================================================================
# Proctor
# ===========================================================================
@app.route("/proctors", methods=["POST"])
def create_proctor():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    institution_id = helpers.require_str(body, "institution_id")
    full_name = helpers.require_str(body, "full_name")
    capacity = helpers.optional_int(body, "concurrent_capacity", default=4, minimum=1)
    fk_or_404(db.institutions, institution_id)
    rec = {
        "id": db.new_id(),
        "institution_id": institution_id,
        "full_name": full_name,
        "concurrent_capacity": capacity,
        "active_session_count": 0,
        "load_factor": 0,
        "status": "AVAILABLE",
    }
    db.stamp_create(rec, versioned=True)
    db.proctors[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/proctors/<proctor_id>", methods=["GET"])
def get_proctor(proctor_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    rec = find_or_404(db.proctors, proctor_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/proctors", methods=["GET"])
def list_proctors():
    _, role = authenticate()
    require_roles(role, [SC, RO])
    limit, offset = helpers.parse_pagination()
    institution_id = request.args.get("institution_id")
    records = [r for r in db.proctors.values()
               if institution_id is None or r["institution_id"] == institution_id]
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


# ===========================================================================
# Candidate
# ===========================================================================
@app.route("/candidates", methods=["POST"])
def create_candidate():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    institution_id = helpers.require_str(body, "institution_id")
    full_name = helpers.require_str(body, "full_name")
    email = helpers.require_str(body, "email")
    fk_or_404(db.institutions, institution_id)
    rec = {
        "id": db.new_id(),
        "institution_id": institution_id,
        "full_name": full_name,
        "email": email,
    }
    db.stamp_create(rec, versioned=True)
    db.candidates[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/candidates/<candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    _, role = authenticate()
    require_roles(role, [SC, CA])
    rec = find_or_404(db.candidates, candidate_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/candidates", methods=["GET"])
def list_candidates():
    _, role = authenticate()
    require_roles(role, [SC])
    limit, offset = helpers.parse_pagination()
    institution_id = request.args.get("institution_id")
    records = [r for r in db.candidates.values()
               if institution_id is None or r["institution_id"] == institution_id]
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


# ===========================================================================
# Exam
# ===========================================================================
@app.route("/exams", methods=["POST"])
def create_exam():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    institution_id = helpers.require_str(body, "institution_id")
    title = helpers.require_str(body, "title")
    base_duration = helpers.require_int(body, "base_duration_minutes", minimum=1)
    window_start = helpers.require_str(body, "window_start_utc")
    window_end = helpers.require_str(body, "window_end_utc")
    monitoring_mode = helpers.require_enum(body, "monitoring_mode", MONITORING_MODES)
    lockdown_required = helpers.optional_bool(body, "lockdown_required", default=True)
    # Validate timestamps parse.
    try:
        parse_iso(window_start)
        parse_iso(window_end)
    except ValueError:
        raise errors.validation("window_start_utc / window_end_utc must be ISO 8601 UTC.")
    fk_or_404(db.institutions, institution_id)
    rec = {
        "id": db.new_id(),
        "institution_id": institution_id,
        "title": title,
        "base_duration_minutes": base_duration,
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "monitoring_mode": monitoring_mode,
        "lockdown_required": lockdown_required,
        "status": "OPEN",
    }
    db.stamp_create(rec, versioned=True)
    db.exams[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/exams/<exam_id>", methods=["GET"])
def get_exam(exam_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, CA])
    rec = find_or_404(db.exams, exam_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/exams", methods=["GET"])
def list_exams():
    _, role = authenticate()
    require_roles(role, [SC, CA])
    limit, offset = helpers.parse_pagination()
    institution_id = request.args.get("institution_id")
    records = [r for r in db.exams.values()
               if institution_id is None or r["institution_id"] == institution_id]
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/exams/<exam_id>/close", methods=["POST"])
def close_exam(exam_id):
    _, role = authenticate()
    require_roles(role, [SC])
    exam = find_or_404(db.exams, exam_id)
    # State: must be OPEN (PRD §3.1). Already CLOSED -> invalid state.
    if exam["status"] != "OPEN":
        raise errors.invalid_state("Exam is not OPEN.")
    # Precondition: no appointment for this exam in SCHEDULED or CHECKED_IN.
    for appt in db.appointments.values():
        if appt["exam_id"] == exam_id and appt["status"] in ("SCHEDULED", "CHECKED_IN"):
            raise errors.invalid_state("Exam has open appointments and cannot be closed.")
    exam["status"] = "CLOSED"
    db.touch(exam)
    return success(public_view(exam), status=200, response_type="object")


# ===========================================================================
# Accommodation
# ===========================================================================
@app.route("/accommodations", methods=["POST"])
def create_accommodation():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    candidate_id = helpers.require_str(body, "candidate_id")
    exam_id = helpers.require_str(body, "exam_id")
    extra_pct = helpers.optional_int(body, "extra_time_pct", default=0, minimum=0, maximum=100)
    # Existence, left-to-right (candidate then exam).
    fk_or_404(db.candidates, candidate_id)
    fk_or_404(db.exams, exam_id)
    rec = {
        "id": db.new_id(),
        "candidate_id": candidate_id,
        "exam_id": exam_id,
        "extra_time_pct": extra_pct,
        "status": "APPROVED",
    }
    db.stamp_create(rec, versioned=True)
    db.accommodations[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/accommodations/<accommodation_id>", methods=["GET"])
def get_accommodation(accommodation_id):
    _, role = authenticate()
    require_roles(role, [SC, CA])
    rec = find_or_404(db.accommodations, accommodation_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/accommodations", methods=["GET"])
def list_accommodations():
    _, role = authenticate()
    require_roles(role, [SC, CA])
    limit, offset = helpers.parse_pagination()
    candidate_id = request.args.get("candidate_id")
    exam_id = request.args.get("exam_id")
    records = []
    for r in db.accommodations.values():
        if candidate_id is not None and r["candidate_id"] != candidate_id:
            continue
        if exam_id is not None and r["exam_id"] != exam_id:
            continue
        records.append(r)
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/accommodations/<accommodation_id>/revoke", methods=["POST"])
def revoke_accommodation(accommodation_id):
    _, role = authenticate()
    require_roles(role, [SC])
    rec = find_or_404(db.accommodations, accommodation_id)
    if rec["status"] != "APPROVED":
        raise errors.invalid_state("Accommodation is not APPROVED.")
    rec["status"] = "REVOKED"
    db.touch(rec)
    return success(public_view(rec), status=200, response_type="object")


# ===========================================================================
# Appointment
# ===========================================================================
@app.route("/appointments", methods=["POST"])
def create_appointment():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    exam_id = helpers.require_str(body, "exam_id")
    candidate_id = helpers.require_str(body, "candidate_id")
    proctor_id = helpers.require_str(body, "proctor_id")
    accommodation_id = helpers.optional_str(body, "accommodation_id", default=None)
    scheduled_start = helpers.require_str(body, "scheduled_start_utc")
    try:
        parse_iso(scheduled_start)
    except ValueError:
        raise errors.validation("scheduled_start_utc must be ISO 8601 UTC.")

    # Existence (priority 3), left-to-right: exam, candidate, proctor, accommodation.
    exam = fk_or_404(db.exams, exam_id)
    candidate = fk_or_404(db.candidates, candidate_id)
    proctor = fk_or_404(db.proctors, proctor_id)
    accommodation = fk_or_404(db.accommodations, accommodation_id)

    # Referential consistency (priority 4): accommodation candidate/exam must
    # match the appointment's candidate/exam.
    if accommodation is not None:
        if accommodation["candidate_id"] != candidate_id or accommodation["exam_id"] != exam_id:
            raise errors.reference_mismatch(
                "Accommodation candidate/exam does not match the appointment."
            )

    # Exam closed gate (PRD §3.2): creation against a CLOSED exam refused.
    if exam["status"] == "CLOSED":
        raise errors.exam_closed()

    # Compute effective window (appointment_effective_window).
    eff_duration, eff_end = services.compute_effective_window(exam, accommodation, scheduled_start)

    # Temporal checks (priority 8, 9, 10) in pinned order.
    if not services.window_fits_exam(exam, scheduled_start, eff_end):
        raise errors.outside_window()
    if services.proctor_overlaps(proctor_id, scheduled_start, eff_end):
        raise errors.proctor_double_booked()
    if services.candidate_overlaps(candidate_id, exam_id, scheduled_start, eff_end):
        raise errors.candidate_overlap()

    rec = {
        "id": db.new_id(),
        "exam_id": exam_id,
        "candidate_id": candidate_id,
        "proctor_id": proctor_id,
        "accommodation_id": accommodation_id,
        "scheduled_start_utc": scheduled_start,
        "effective_duration_minutes": eff_duration,
        "effective_end_utc": eff_end,
        "status": "SCHEDULED",
        "superseded_by_id": None,
    }
    db.stamp_create(rec, versioned=True)
    db.appointments[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, CA, PR])
    rec = find_or_404(db.appointments, appointment_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/appointments", methods=["GET"])
def list_appointments():
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    limit, offset = helpers.parse_pagination()
    filters = {
        "exam_id": request.args.get("exam_id"),
        "candidate_id": request.args.get("candidate_id"),
        "proctor_id": request.args.get("proctor_id"),
        "accommodation_id": request.args.get("accommodation_id"),
        "superseded_by_id": request.args.get("superseded_by_id"),
        "status": request.args.get("status"),
    }
    records = []
    for r in db.appointments.values():
        if any(v is not None and r.get(k) != v for k, v in filters.items()):
            continue
        records.append(r)
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/appointments/<appointment_id>/verify-identity", methods=["POST"])
def verify_identity(appointment_id):
    _, role = authenticate()
    require_roles(role, [CA, PR])
    appt = find_or_404(db.appointments, appointment_id)
    body = helpers.get_json_body()
    photo_id_match = helpers.require_bool(body, "photo_id_match")
    room_scan_clear = helpers.require_bool(body, "room_scan_clear")
    # result = PASS if both true else FAIL.
    result = "PASS" if (photo_id_match and room_scan_clear) else "FAIL"
    rec = {
        "id": db.new_id(),
        "appointment_id": appt["id"],
        "photo_id_match": photo_id_match,
        "room_scan_clear": room_scan_clear,
        "result": result,
    }
    db.stamp_create(rec, versioned=False)  # append-only: id + created_at only
    db.identity_verifications[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/appointments/<appointment_id>/identity-verifications", methods=["GET"])
def list_identity_verifications(appointment_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, CA, PR])
    find_or_404(db.appointments, appointment_id)
    limit, offset = helpers.parse_pagination()
    records = [r for r in db.identity_verifications.values()
               if r["appointment_id"] == appointment_id]
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/appointments/<appointment_id>/check-in", methods=["POST"])
def check_in(appointment_id):
    _, role = authenticate()
    require_roles(role, [CA])
    appt = find_or_404(db.appointments, appointment_id)
    exam = db.exams[appt["exam_id"]]
    proctor = db.proctors[appt["proctor_id"]]

    # State (priority 5): appointment must be SCHEDULED.
    if appt["status"] != "SCHEDULED":
        raise errors.invalid_state("Appointment is not SCHEDULED.")

    # Lockdown gate (priority 7): when lockdown_required, a PASS verification
    # must exist for the appointment.
    if exam["lockdown_required"]:
        has_pass = any(
            v["appointment_id"] == appointment_id and v["result"] == "PASS"
            for v in db.identity_verifications.values()
        )
        if not has_pass:
            raise errors.lockdown_not_verified()

    # Temporal gate: clock >= scheduled_start_utc (ERR_CHECKIN_TOO_EARLY).
    if get_logical_now() < parse_iso(appt["scheduled_start_utc"]):
        raise errors.checkin_too_early("Check-in attempted before scheduled_start_utc.")

    # Capacity (priority 11): prospective load with the new session <= 1.0.
    new_mode = exam["monitoring_mode"]
    if not services.prospective_load_ok(proctor, new_mode):
        raise errors.proctor_overloaded()

    # Admit session.
    appt["status"] = "CHECKED_IN"
    db.touch(appt)
    session = {
        "id": db.new_id(),
        "appointment_id": appt["id"],
        "proctor_id": appt["proctor_id"],
        "monitoring_mode": new_mode,
        "integrity_score": 100,
        "status": "ACTIVE",
        "void_reason": None,
    }
    db.stamp_create(session, versioned=True)
    db.sessions[session["id"]] = session
    # Recompute proctor denorm to include the new session.
    services.refresh_proctor_denorm(proctor)
    db.touch(proctor)
    return success(public_view(session), status=201, response_type="object")


@app.route("/appointments/<appointment_id>/mark-no-show", methods=["POST"])
def mark_no_show(appointment_id):
    _, role = authenticate()
    require_roles(role, [PR, SC])
    appt = find_or_404(db.appointments, appointment_id)
    # State: must be SCHEDULED.
    if appt["status"] != "SCHEDULED":
        raise errors.invalid_state("Appointment is not SCHEDULED.")
    # Temporal gate: clock >= effective_end_utc.
    if get_logical_now() < parse_iso(appt["effective_end_utc"]):
        raise errors.checkin_too_early("No-show attempted before effective_end_utc.")
    appt["status"] = "NO_SHOW"
    db.touch(appt)
    return success(public_view(appt), status=200, response_type="object")


@app.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    _, role = authenticate()
    require_roles(role, [SC])
    appt = find_or_404(db.appointments, appointment_id)
    # State: must be SCHEDULED or CHECKED_IN.
    if appt["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise errors.invalid_state("Appointment is not SCHEDULED or CHECKED_IN.")
    # Cancellation refused if a non-terminal session (ACTIVE/PAUSED) exists.
    for s in db.sessions.values():
        if s["appointment_id"] == appointment_id and s["status"] in ("ACTIVE", "PAUSED"):
            raise errors.session_in_progress()
    appt["status"] = "CANCELLED"
    db.touch(appt)
    return success(public_view(appt), status=200, response_type="object")


# ===========================================================================
# ProctoringSession
# ===========================================================================
@app.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    rec = find_or_404(db.sessions, session_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/sessions", methods=["GET"])
def list_sessions():
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    limit, offset = helpers.parse_pagination()
    appointment_id = request.args.get("appointment_id")
    proctor_id = request.args.get("proctor_id")
    status = request.args.get("status")
    records = []
    for r in db.sessions.values():
        if appointment_id is not None and r["appointment_id"] != appointment_id:
            continue
        if proctor_id is not None and r["proctor_id"] != proctor_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/sessions/<session_id>/flags", methods=["POST"])
def raise_flag(session_id):
    _, role = authenticate()
    require_roles(role, [PR])
    session = find_or_404(db.sessions, session_id)
    body = helpers.get_json_body()
    kind = helpers.require_enum(body, "kind", FLAG_KINDS)
    severity = helpers.require_enum(body, "severity", SEVERITIES)
    # State: a flag can be raised on a session that is being monitored; reject
    # if the session is terminal (PRD §3.5 raising during a session).
    if session["status"] in SESSION_TERMINAL:
        raise errors.invalid_state("Session is terminal; no flags may be raised.")

    flag = {
        "id": db.new_id(),
        "session_id": session_id,
        "kind": kind,
        "severity": severity,
        "status": "OPEN",
    }
    db.stamp_create(flag, versioned=False)  # append-only: id + created_at only
    db.incident_flags[flag["id"]] = flag

    # Recompute integrity score from counting flags.
    new_score = services.compute_integrity_score(session)
    # Auto-void if score strictly < 50 (exactly 50 does not trigger).
    if new_score < services.AUTO_VOID_THRESHOLD:
        services.void_session(session, void_reason="AUTO_THRESHOLD")
    else:
        services.refresh_integrity_score(session)
        # Recomputing a computed field does not bump version on its own, but
        # the score moved as a result of this mutation; persist it.
        db.touch(session)
    return success(public_view(flag), status=201, response_type="object")


@app.route("/sessions/<session_id>/flags", methods=["GET"])
def list_flags(session_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    find_or_404(db.sessions, session_id)
    limit, offset = helpers.parse_pagination()
    records = [r for r in db.incident_flags.values() if r["session_id"] == session_id]
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/sessions/<session_id>/pause", methods=["POST"])
def pause_session(session_id):
    _, role = authenticate()
    require_roles(role, [PR])
    session = find_or_404(db.sessions, session_id)
    if session["status"] != "ACTIVE":
        raise errors.invalid_state("Session is not ACTIVE.")
    session["status"] = "PAUSED"
    db.touch(session)
    return success(public_view(session), status=200, response_type="object")


@app.route("/sessions/<session_id>/resume", methods=["POST"])
def resume_session(session_id):
    _, role = authenticate()
    require_roles(role, [PR])
    session = find_or_404(db.sessions, session_id)
    if session["status"] != "PAUSED":
        raise errors.invalid_state("Session is not PAUSED.")
    session["status"] = "ACTIVE"
    db.touch(session)
    return success(public_view(session), status=200, response_type="object")


@app.route("/sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    _, role = authenticate()
    require_roles(role, [PR])
    session = find_or_404(db.sessions, session_id)
    # State: only from ACTIVE.
    if session["status"] != "ACTIVE":
        raise errors.invalid_state("Session is not ACTIVE.")
    # No escalation on it still OPEN or UNDER_REVIEW.
    for esc in db.escalations.values():
        if esc["session_id"] == session_id and esc["status"] in ("OPEN", "UNDER_REVIEW"):
            raise errors.invalid_state("An open escalation exists on this session.")
    # Freeze final integrity_score.
    services.refresh_integrity_score(session)
    session["status"] = "COMPLETED"
    db.touch(session)
    # Appointment -> CONSUMED.
    appt = db.appointments.get(session["appointment_id"])
    if appt is not None:
        services.consume_appointment(appt)
    # Proctor denorm recomputed.
    proctor = db.proctors.get(session["proctor_id"])
    if proctor is not None:
        services.refresh_proctor_denorm(proctor)
        db.touch(proctor)
    return success(public_view(session), status=200, response_type="object")


# ===========================================================================
# Escalation
# ===========================================================================
@app.route("/escalations", methods=["POST"])
def open_escalation():
    user_id, role = authenticate()
    require_roles(role, [PR])
    body = helpers.get_json_body()
    session_id = helpers.require_str(body, "session_id")
    incident_flag_id = helpers.require_str(body, "incident_flag_id")
    # Existence left-to-right: session then incident flag.
    session = fk_or_404(db.sessions, session_id)
    flag = fk_or_404(db.incident_flags, incident_flag_id)
    # State: session must be ACTIVE or PAUSED to be held for review.
    if session["status"] not in ("ACTIVE", "PAUSED"):
        raise errors.invalid_state("Session is not in a holdable state.")

    esc = {
        "id": db.new_id(),
        "session_id": session_id,
        "incident_flag_id": incident_flag_id,
        "opened_by_proctor_id": user_id,
        "review_officer_id": None,
        "verdict": None,
        "status": "OPEN",
    }
    db.stamp_create(esc, versioned=True)
    db.escalations[esc["id"]] = esc
    # Session -> REVIEW_HELD; triggering flag -> ESCALATED.
    session["status"] = "REVIEW_HELD"
    db.touch(session)
    flag["status"] = "ESCALATED"
    return success(public_view(esc), status=201, response_type="object")


@app.route("/escalations/<escalation_id>", methods=["GET"])
def get_escalation(escalation_id):
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    rec = find_or_404(db.escalations, escalation_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/escalations", methods=["GET"])
def list_escalations():
    _, role = authenticate()
    require_roles(role, [SC, RO, PR])
    limit, offset = helpers.parse_pagination()
    filters = {
        "session_id": request.args.get("session_id"),
        "incident_flag_id": request.args.get("incident_flag_id"),
        "opened_by_proctor_id": request.args.get("opened_by_proctor_id"),
        "review_officer_id": request.args.get("review_officer_id"),
        "status": request.args.get("status"),
    }
    records = []
    for r in db.escalations.values():
        if any(v is not None and r.get(k) != v for k, v in filters.items()):
            continue
        records.append(r)
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/escalations/<escalation_id>/claim", methods=["POST"])
def claim_escalation(escalation_id):
    user_id, role = authenticate()
    require_roles(role, [RO])
    esc = find_or_404(db.escalations, escalation_id)
    # State: only OPEN can be claimed.
    if esc["status"] != "OPEN":
        raise errors.invalid_state("Escalation is not OPEN.")
    # Segregation of duties: acting officer != opener.
    if user_id == esc["opened_by_proctor_id"]:
        raise errors.segregation("A review officer cannot claim an escalation they opened.")
    esc["review_officer_id"] = user_id
    esc["status"] = "UNDER_REVIEW"
    db.touch(esc)  # increments version by 1
    return success(public_view(esc), status=200, response_type="object")


@app.route("/escalations/<escalation_id>/decide", methods=["POST"])
def decide_escalation(escalation_id):
    user_id, role = authenticate()
    require_roles(role, [RO])
    esc = find_or_404(db.escalations, escalation_id)
    body = helpers.get_json_body()
    verdict = helpers.require_enum(body, "verdict", VERDICTS)
    expected_version = helpers.require_int(body, "expected_escalation_version")
    # State: must be UNDER_REVIEW.
    if esc["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Escalation is not UNDER_REVIEW.")
    # Segregation / authorization: acting officer must be the review officer.
    if user_id != esc["review_officer_id"]:
        raise errors.segregation("Only the assigned review officer may decide this escalation.")
    # OCC last (priority 13): expected_escalation_version must match current.
    if expected_version != esc["version"]:
        raise errors.stale_version()

    session = db.sessions.get(esc["session_id"])
    flag = db.incident_flags.get(esc["incident_flag_id"])

    esc["verdict"] = verdict
    esc["status"] = verdict  # UPHELD or DISMISSED
    db.touch(esc)  # increments version by 1

    if verdict == "UPHELD":
        # Session REVIEW_HELD -> VOIDED (ESCALATION_UPHELD); triggering flag
        # RESOLVED; appointment CONSUMED; proctor load recomputed.
        if session is not None:
            services.void_session(
                session, void_reason="ESCALATION_UPHELD",
                resolve_only_flag_id=esc["incident_flag_id"],
            )
    else:  # DISMISSED
        # Triggering flag -> RESOLVED; session REVIEW_HELD -> ACTIVE (when no
        # other escalation on the session is still open/under-review);
        # integrity_score recomputed.
        if flag is not None:
            flag["status"] = "RESOLVED"
        if session is not None:
            others_open = any(
                e["session_id"] == session["id"] and e["id"] != esc["id"]
                and e["status"] in ("OPEN", "UNDER_REVIEW")
                for e in db.escalations.values()
            )
            if session["status"] == "REVIEW_HELD" and not others_open:
                session["status"] = "ACTIVE"
            services.refresh_integrity_score(session)
            db.touch(session)
    return success(public_view(esc), status=200, response_type="object")


# ===========================================================================
# IntegrityReport
# ===========================================================================
@app.route("/integrity-reports", methods=["POST"])
def create_report():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    institution_id = helpers.require_str(body, "institution_id")
    candidate_id = helpers.require_str(body, "candidate_id")
    exam_id = helpers.require_str(body, "exam_id")
    session_ids = helpers.require_array(body, "session_ids")

    # Existence left-to-right: institution, candidate, exam, then each session.
    fk_or_404(db.institutions, institution_id)
    fk_or_404(db.candidates, candidate_id)
    fk_or_404(db.exams, exam_id)
    for sid in session_ids:
        if not isinstance(sid, str):
            raise errors.validation("session_ids must be an array of strings.")
        fk_or_404(db.sessions, sid)

    # Referential consistency (priority 4): each session's appointment must
    # belong to report.candidate_id AND report.institution_id.
    for sid in session_ids:
        session = db.sessions[sid]
        appt = db.appointments.get(session["appointment_id"])
        if appt is None or appt["candidate_id"] != candidate_id:
            raise errors.reference_mismatch("A report session does not belong to the candidate.")
        sess_exam = db.exams.get(appt["exam_id"])
        if sess_exam is None or sess_exam["institution_id"] != institution_id:
            raise errors.reference_mismatch("A report session does not belong to the institution.")

    # Content constraint (priority 12): non-empty and every session terminal.
    if len(session_ids) == 0:
        raise errors.empty_report("Report session_ids must be non-empty.")
    for sid in session_ids:
        if db.sessions[sid]["status"] not in SESSION_TERMINAL:
            raise errors.empty_report("A referenced session is not terminal.")

    rec = {
        "id": db.new_id(),
        "institution_id": institution_id,
        "candidate_id": candidate_id,
        "exam_id": exam_id,
        "session_ids": list(session_ids),
        "aggregate_score": None,
        "disposition": None,
        "status": "DRAFT",
    }
    db.stamp_create(rec, versioned=True)
    db.integrity_reports[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/integrity-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    _, role = authenticate()
    require_roles(role, [SC, RO])
    rec = find_or_404(db.integrity_reports, report_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/integrity-reports", methods=["GET"])
def list_reports():
    _, role = authenticate()
    require_roles(role, [SC, RO])
    limit, offset = helpers.parse_pagination()
    filters = {
        "institution_id": request.args.get("institution_id"),
        "candidate_id": request.args.get("candidate_id"),
        "exam_id": request.args.get("exam_id"),
        "status": request.args.get("status"),
    }
    records = []
    for r in db.integrity_reports.values():
        if any(v is not None and r.get(k) != v for k, v in filters.items()):
            continue
        records.append(r)
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/integrity-reports/<report_id>/deliver", methods=["POST"])
def deliver_report(report_id):
    _, role = authenticate()
    require_roles(role, [SC])
    report = find_or_404(db.integrity_reports, report_id)
    # State: must be DRAFT.
    if report["status"] != "DRAFT":
        raise errors.invalid_state("Report is not DRAFT.")
    session_ids = report["session_ids"]
    # Content constraint (priority 12): non-empty and every session terminal.
    if len(session_ids) == 0:
        raise errors.empty_report("Report session_ids must be non-empty.")
    for sid in session_ids:
        session = db.sessions.get(sid)
        if session is None or session["status"] not in SESSION_TERMINAL:
            raise errors.empty_report("A referenced session is not terminal.")
    # Compute aggregate + disposition (per-session-round pinned order).
    aggregate = services.compute_aggregate_score(session_ids)
    institution = db.institutions[report["institution_id"]]
    threshold = institution["report_threshold_score"]
    disposition = "CLEARED" if aggregate >= threshold else "ESCALATED_TO_INSTITUTION"
    report["aggregate_score"] = services._as_number(aggregate)
    report["disposition"] = disposition
    report["status"] = "DELIVERED"
    db.touch(report)
    return success(public_view(report), status=200, response_type="object")


# ===========================================================================
# RetakeAuthorization
# ===========================================================================
@app.route("/retake-authorizations", methods=["POST"])
def create_retake():
    user_id, role = authenticate()
    require_roles(role, [RO])
    body = helpers.get_json_body()
    voided_session_id = helpers.require_str(body, "voided_session_id")
    session = fk_or_404(db.sessions, voided_session_id)
    # State: the session must actually be VOIDED.
    if session["status"] != "VOIDED":
        raise errors.not_voided()
    # Segregation of duties: the officer who upheld the escalation that voided
    # this session may not author its retake.
    if session.get("void_reason") == "ESCALATION_UPHELD":
        for esc in db.escalations.values():
            if (esc["session_id"] == voided_session_id
                    and esc["verdict"] == "UPHELD"
                    and esc["review_officer_id"] == user_id):
                raise errors.segregation(
                    "The upholding officer may not author the retake."
                )
    appt = db.appointments.get(session["appointment_id"])
    rec = {
        "id": db.new_id(),
        "voided_session_id": voided_session_id,
        "original_appointment_id": session["appointment_id"],
        "replacement_appointment_id": None,
        "authorized_by_id": user_id,
        "status": "AUTHORIZED",
    }
    db.stamp_create(rec, versioned=True)
    db.retake_authorizations[rec["id"]] = rec
    return success(public_view(rec), status=201, response_type="object")


@app.route("/retake-authorizations/<retake_id>", methods=["GET"])
def get_retake(retake_id):
    _, role = authenticate()
    require_roles(role, [SC, RO])
    rec = find_or_404(db.retake_authorizations, retake_id)
    return success(public_view(rec), status=200, response_type="object")


@app.route("/retake-authorizations", methods=["GET"])
def list_retakes():
    _, role = authenticate()
    require_roles(role, [SC, RO])
    limit, offset = helpers.parse_pagination()
    filters = {
        "voided_session_id": request.args.get("voided_session_id"),
        "original_appointment_id": request.args.get("original_appointment_id"),
        "replacement_appointment_id": request.args.get("replacement_appointment_id"),
        "authorized_by_id": request.args.get("authorized_by_id"),
        "status": request.args.get("status"),
    }
    records = []
    for r in db.retake_authorizations.values():
        if any(v is not None and r.get(k) != v for k, v in filters.items()):
            continue
        records.append(r)
    page, total = helpers.paginate(records, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@app.route("/retake-authorizations/<retake_id>/rebook", methods=["POST"])
def rebook_retake(retake_id):
    _, role = authenticate()
    require_roles(role, [SC])
    retake = find_or_404(db.retake_authorizations, retake_id)
    body = helpers.get_json_body()
    proctor_id = helpers.require_str(body, "proctor_id")
    scheduled_start = helpers.require_str(body, "scheduled_start_utc")
    accommodation_id = helpers.optional_str(body, "accommodation_id", default=None)
    expected_version = helpers.require_int(body, "expected_appointment_version")
    try:
        parse_iso(scheduled_start)
    except ValueError:
        raise errors.validation("scheduled_start_utc must be ISO 8601 UTC.")

    # Existence: proctor, accommodation (body FKs).
    proctor = fk_or_404(db.proctors, proctor_id)
    accommodation = fk_or_404(db.accommodations, accommodation_id)

    original = db.appointments.get(retake["original_appointment_id"])
    if original is None:
        raise errors.not_found()
    exam = db.exams[original["exam_id"]]
    candidate_id = original["candidate_id"]
    exam_id = original["exam_id"]

    # State: retake must be AUTHORIZED; original CONSUMED & not superseded.
    if retake["status"] != "AUTHORIZED":
        raise errors.invalid_state("Retake authorization is not AUTHORIZED.")
    if original["status"] != "CONSUMED" or original["superseded_by_id"] is not None:
        raise errors.invalid_state("Original appointment is not in a rebookable state.")

    # Referential consistency (priority 4): if accommodation supplied it must
    # match the original candidate + exam.
    if accommodation is not None:
        if accommodation["candidate_id"] != candidate_id or accommodation["exam_id"] != exam_id:
            raise errors.reference_mismatch(
                "Accommodation candidate/exam does not match the appointment."
            )

    # Compute replacement effective window.
    eff_duration, eff_end = services.compute_effective_window(exam, accommodation, scheduled_start)

    # Temporal checks (priority 8, 9, 10), then OCC last (priority 13).
    if not services.window_fits_exam(exam, scheduled_start, eff_end):
        raise errors.outside_window()
    if services.proctor_overlaps(proctor_id, scheduled_start, eff_end):
        raise errors.proctor_double_booked()
    if services.candidate_overlaps(candidate_id, exam_id, scheduled_start, eff_end):
        raise errors.candidate_overlap()

    # OCC (priority 13): expected_appointment_version must equal original.version.
    if expected_version != original["version"]:
        raise errors.stale_version()

    # Create the replacement appointment (SCHEDULED) for same exam + candidate.
    replacement = {
        "id": db.new_id(),
        "exam_id": exam_id,
        "candidate_id": candidate_id,
        "proctor_id": proctor_id,
        "accommodation_id": accommodation_id,
        "scheduled_start_utc": scheduled_start,
        "effective_duration_minutes": eff_duration,
        "effective_end_utc": eff_end,
        "status": "SCHEDULED",
        "superseded_by_id": None,
    }
    db.stamp_create(replacement, versioned=True)
    db.appointments[replacement["id"]] = replacement

    # Original superseded in place: set superseded_by_id, bump version (status
    # stays CONSUMED).
    original["superseded_by_id"] = replacement["id"]
    db.touch(original)

    # Retake -> REBOOKED, replacement_appointment_id set.
    retake["status"] = "REBOOKED"
    retake["replacement_appointment_id"] = replacement["id"]
    db.touch(retake)

    return success(public_view(replacement), status=201, response_type="object")


@app.route("/retake-authorizations/<retake_id>/expire", methods=["POST"])
def expire_retake(retake_id):
    _, role = authenticate()
    require_roles(role, [SC])
    retake = find_or_404(db.retake_authorizations, retake_id)
    if retake["status"] != "AUTHORIZED":
        raise errors.invalid_state("Retake authorization is not AUTHORIZED.")
    retake["status"] = "EXPIRED"
    db.touch(retake)
    return success(public_view(retake), status=200, response_type="object")


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_roles(role, [SC])
    body = helpers.get_json_body()
    to_iso = helpers.require_str(body, "to_iso8601")
    try:
        set_logical_now(to_iso)
    except ValueError:
        raise errors.validation("to_iso8601 must be ISO 8601 UTC.")
    # output: null -> empty object in data per envelope rules.
    return success({}, status=200, response_type="object")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
