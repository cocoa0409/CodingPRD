"""CDL & Truck-Driving School API — entry point and all routes.

Flat top-level resource collections, in-memory store, logical clock.
Validation ordering follows PRD §2.8.
"""
import os

from flask import Flask, request

import errors
from errors import ApiError
from db import db, stamp_create, touch
from clock import clock
from middleware import require_roles
from response import object_response, array_response, error_response
from util import parse_iso8601, iso_now
import serializers as S
import validate as V
import services as SV

app = Flask(__name__)

CDL_CLASSES = {"CLASS_A", "CLASS_B"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Lookup helpers (existence — priority 3, ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def _get_or_404(coll, ident):
    rec = coll.get(ident)
    if rec is None:
        raise errors.not_found()
    return rec


def get_program(i): return _get_or_404(db.programs, i)
def get_truck(i): return _get_or_404(db.trucks, i)
def get_instructor(i): return _get_or_404(db.instructors, i)
def get_enrollment(i): return _get_or_404(db.enrollments, i)
def get_prereq(i): return _get_or_404(db.prereq_documents, i)
def get_session(i): return _get_or_404(db.clock_sessions, i)
def get_skills_test(i): return _get_or_404(db.skills_tests, i)
def get_carrier(i): return _get_or_404(db.carriers, i)
def get_offer(i): return _get_or_404(db.sponsorship_offers, i)
def get_finance_plan(i): return _get_or_404(db.finance_plans, i)
def get_completion_report(i): return _get_or_404(db.completion_reports, i)


def _list_response(records, serializer):
    limit, offset = V.pagination_params()
    window, total = V.paginate(records, limit, offset)
    return array_response([serializer(r) for r in window], limit, offset, total)


# ===========================================================================
# Program
# ===========================================================================
@app.post("/programs")
@require_roles("SchoolAdmin")
def create_program():
    body = V.get_json_body()
    name = V.require_str(body, "name")
    cdl_class = V.require_enum(body, "cdl_class", CDL_CLASSES)
    classroom = V.require_number(body, "classroom_required_hours", minimum=0)
    range_h = V.require_number(body, "range_required_hours", minimum=0)
    road = V.require_number(body, "road_required_hours", minimum=0)
    tuition = V.require_int(body, "tuition_cents", minimum=0)
    threshold = V.opt_number(body, "skills_pass_threshold", 80, minimum=0, maximum=100)
    rec = stamp_create({
        "name": name, "cdl_class": cdl_class,
        "classroom_required_hours": classroom, "range_required_hours": range_h,
        "road_required_hours": road, "tuition_cents": tuition,
        "skills_pass_threshold": threshold, "active": True,
    })
    db.programs[rec["id"]] = rec
    return object_response(S.program_out(rec), 201)


@app.get("/programs/<pid>")
@require_roles("SchoolAdmin", "Registrar", "Instructor", "ThirdPartyExaminer")
def read_program(pid):
    return object_response(S.program_out(get_program(pid)))


# ===========================================================================
# Truck
# ===========================================================================
@app.post("/trucks")
@require_roles("SchoolAdmin")
def create_truck():
    body = V.get_json_body()
    unit = V.require_str(body, "unit_number")
    cdl_class = V.require_enum(body, "cdl_class", CDL_CLASSES)
    buffer = V.opt_int(body, "turnaround_buffer_minutes", 30, minimum=0)
    rec = stamp_create({
        "unit_number": unit, "cdl_class": cdl_class,
        "turnaround_buffer_minutes": buffer,
        "status": "AVAILABLE", "reserved_minutes": 0,
    })
    db.trucks[rec["id"]] = rec
    return object_response(S.truck_out(rec), 201)


@app.get("/trucks/<tid>")
@require_roles("SchoolAdmin", "Registrar", "Instructor")
def read_truck(tid):
    return object_response(S.truck_out(get_truck(tid)))


# ===========================================================================
# Instructor
# ===========================================================================
@app.post("/instructors")
@require_roles("SchoolAdmin")
def create_instructor():
    body = V.get_json_body()
    full_name = V.require_str(body, "full_name")
    cdl_class = V.require_enum(body, "cdl_class", CDL_CLASSES)
    examiner = V.opt_bool(body, "examiner_certified", False)
    rec = stamp_create({
        "full_name": full_name, "cdl_class": cdl_class,
        "examiner_certified": examiner,
        "status": "ACTIVE", "reserved_minutes": 0,
    })
    db.instructors[rec["id"]] = rec
    return object_response(S.instructor_out(rec), 201)


@app.get("/instructors/<iid>")
@require_roles("SchoolAdmin", "Registrar", "Instructor", "ThirdPartyExaminer")
def read_instructor(iid):
    return object_response(S.instructor_out(get_instructor(iid)))


# ===========================================================================
# Carrier
# ===========================================================================
@app.post("/carriers")
@require_roles("SchoolAdmin")
def create_carrier():
    body = V.get_json_body()
    name = V.require_str(body, "name")
    commitment = V.require_int(body, "commitment_months", gt=0)
    reimbursement = V.require_int(body, "reimbursement_cents", minimum=0)
    rec = stamp_create({
        "name": name, "commitment_months": commitment,
        "reimbursement_cents": reimbursement,
    })
    db.carriers[rec["id"]] = rec
    return object_response(S.carrier_out(rec), 201)


@app.get("/carriers/<cid>")
@require_roles("SchoolAdmin", "Registrar")
def read_carrier(cid):
    return object_response(S.carrier_out(get_carrier(cid)))


# ===========================================================================
# Enrollment
# ===========================================================================
@app.post("/enrollments")
@require_roles("Registrar")
def create_enrollment():
    body = V.get_json_body()
    # FK existence (priority 3) before remaining well-formedness (priority 4)
    program_id = V.fk_value(body, "program_id")
    get_program(program_id)
    student_name = V.require_str(body, "student_name")
    rec = stamp_create({
        "program_id": program_id, "student_name": student_name,
        "dot_medical_verified": False, "permit_verified": False,
        "status": "APPLIED",
        "logged_classroom_hours": 0.0, "logged_range_hours": 0.0,
        "logged_road_hours": 0.0, "projected_road_hours": 0.0,
        "sponsoring_carrier_id": None, "fmcsa_reported": False,
    })
    db.enrollments[rec["id"]] = rec
    return object_response(S.enrollment_out(rec), 201)


@app.get("/enrollments")
@require_roles("SchoolAdmin", "Registrar")
def list_enrollments():
    program_id = request.args.get("program_id")
    carrier_id = request.args.get("sponsoring_carrier_id")
    recs = list(db.enrollments.values())
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if carrier_id is not None:
        recs = [r for r in recs if r.get("sponsoring_carrier_id") == carrier_id]
    return _list_response(recs, S.enrollment_out)


@app.get("/enrollments/<eid>")
@require_roles("SchoolAdmin", "Registrar", "Instructor", "ThirdPartyExaminer")
def read_enrollment(eid):
    return object_response(S.enrollment_out(get_enrollment(eid)))


@app.post("/enrollments/<eid>/withdraw")
@require_roles("Registrar")
def withdraw_enrollment(eid):
    enr = get_enrollment(eid)
    # State: not from COMPLETED or already WITHDRAWN (terminal)
    if enr["status"] in ("COMPLETED", "WITHDRAWN"):
        raise errors.invalid_state("Enrollment is terminal; cannot withdraw")
    enr["status"] = "WITHDRAWN"
    touch(enr)
    # Cascade: cancel BOOKED sessions + release reserved minutes
    SV.cancel_booked_sessions(enr)
    # ACTIVE FinancePlan -> CANCELLED
    for fp in db.finance_plans.values():
        if fp["enrollment_id"] == eid and fp["status"] == "ACTIVE":
            fp["status"] = "CANCELLED"
            touch(fp)
    # ACCEPTED SponsorshipOffer -> FORFEITED with clawback
    for offer in db.sponsorship_offers.values():
        if offer["enrollment_id"] == eid and offer["status"] == "ACCEPTED":
            SV.forfeit_offer(offer)
    return object_response(S.enrollment_out(enr))


# ===========================================================================
# PrereqDocument
# ===========================================================================
@app.post("/enrollments/<eid>/prereq-documents")
@require_roles("Registrar")
def submit_prereq(eid):
    enr = get_enrollment(eid)
    body = V.get_json_body()
    kind = V.require_enum(body, "kind", {"DOT_MEDICAL", "CLP_PERMIT"})
    ref = V.require_str(body, "reference_code")
    expires_raw = V.require_str(body, "expires_on")
    expires_dt = parse_iso8601(expires_raw, "expires_on")
    rec = stamp_create({
        "enrollment_id": eid, "kind": kind, "reference_code": ref,
        "expires_on": iso_now(expires_dt), "status": "SUBMITTED",
    })
    db.prereq_documents[rec["id"]] = rec
    # APPLIED -> PREREQ_PENDING on first document submission
    if enr["status"] == "APPLIED":
        enr["status"] = "PREREQ_PENDING"
        touch(enr)
    return object_response(S.prereq_document_out(rec), 201)


@app.get("/enrollments/<eid>/prereq-documents")
@require_roles("SchoolAdmin", "Registrar")
def list_prereq_for_enrollment(eid):
    get_enrollment(eid)
    recs = [d for d in db.prereq_documents.values() if d["enrollment_id"] == eid]
    return _list_response(recs, S.prereq_document_out)


@app.get("/prereq-documents")
@require_roles("SchoolAdmin", "Registrar")
def list_prereq():
    enrollment_id = request.args.get("enrollment_id")
    recs = list(db.prereq_documents.values())
    if enrollment_id is not None:
        recs = [d for d in recs if d["enrollment_id"] == enrollment_id]
    return _list_response(recs, S.prereq_document_out)


@app.get("/prereq-documents/<did>")
@require_roles("SchoolAdmin", "Registrar")
def read_prereq(did):
    return object_response(S.prereq_document_out(get_prereq(did)))


@app.post("/prereq-documents/<did>/approve")
@require_roles("Registrar")
def approve_prereq(did):
    doc = get_prereq(did)
    if doc["status"] != "SUBMITTED":
        raise errors.invalid_state("Document is not SUBMITTED")
    # Business safety: expires_on must be strictly after current clock time
    exp = parse_iso8601(doc["expires_on"])
    if exp <= clock.now():
        raise ApiError(errors.ERR_DOCUMENT_EXPIRED, 409,
                       "Cannot approve a document at or past its expiry")
    doc["status"] = "APPROVED"
    touch(doc)
    enr = db.enrollments.get(doc["enrollment_id"])
    if enr:
        if doc["kind"] == "DOT_MEDICAL":
            enr["dot_medical_verified"] = True
        elif doc["kind"] == "CLP_PERMIT":
            enr["permit_verified"] = True
        touch(enr)
        SV.evaluate_prereq_gate(enr)
    return object_response(S.prereq_document_out(doc))


@app.post("/prereq-documents/<did>/reject")
@require_roles("Registrar")
def reject_prereq(did):
    doc = get_prereq(did)
    if doc["status"] != "SUBMITTED":
        raise errors.invalid_state("Document is not SUBMITTED")
    doc["status"] = "REJECTED"
    touch(doc)
    return object_response(S.prereq_document_out(doc))


@app.post("/prereq-documents/<did>/expire")
@require_roles("Registrar", "SchoolAdmin")
def expire_prereq(did):
    doc = get_prereq(did)
    if doc["status"] != "APPROVED":
        raise errors.invalid_state("Document is not APPROVED")
    # Manual expiry is an explicit admin/registrar override of an APPROVED
    # document; the only state precondition is that it is currently APPROVED.
    # (The automatic, clock-driven path in §3.8 separately gates on
    # current clock time >= expires_on.)
    SV.apply_document_expiry(doc)
    return object_response(S.prereq_document_out(doc))


# ===========================================================================
# ClockSession
# ===========================================================================
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


@app.post("/enrollments/<eid>/clock-sessions")
@require_roles("Registrar", "Instructor")
def book_session(eid):
    enr = get_enrollment(eid)
    body = V.get_json_body()

    # Existence (priority 3): present FK values resolve before body
    # well-formedness (priority 4).
    instructor_id = V.fk_value(body, "instructor_id")
    truck_id = V.fk_value(body, "truck_id", required=False)
    instr = get_instructor(instructor_id)
    truck = None
    if truck_id is not None:
        truck = get_truck(truck_id)

    # Body well-formedness (priority 4)
    phase = V.require_enum(body, "phase", {"CLASSROOM", "RANGE", "ROAD"})
    starts_raw = V.require_str(body, "starts_at")
    starts_at = parse_iso8601(starts_raw, "starts_at")
    duration = V.require_int(body, "duration_minutes", gt=0)

    program = db.programs.get(enr["program_id"])

    # Business state: enrollment must be TRAINING (priority 8)
    if enr["status"] != "TRAINING":
        raise ApiError(errors.ERR_PREREQ_NOT_MET, 409,
                       "Enrollment is not in TRAINING")

    # Truck class / classroom rules (priority 11)
    if phase == "CLASSROOM":
        if truck_id is not None:
            raise ApiError(errors.ERR_TRUCK_CLASS_MISMATCH, 409,
                           "CLASSROOM session must not supply a truck_id")
    else:  # RANGE or ROAD
        if truck_id is None:
            raise ApiError(errors.ERR_TRUCK_CLASS_MISMATCH, 409,
                           "RANGE/ROAD session requires a truck_id")
        if truck["cdl_class"] != program["cdl_class"]:
            raise ApiError(errors.ERR_TRUCK_CLASS_MISMATCH, 409,
                           "Truck cdl_class does not match program")

    new_start = starts_at
    new_end_self = starts_at + _minutes(duration)  # [start, start+duration)

    # Truck double-booking (priority 12): buffered interval on existing sessions
    if truck is not None:
        buf = truck.get("turnaround_buffer_minutes", 0)
        for s in db.clock_sessions.values():
            if s.get("truck_id") == truck_id and s["status"] == "BOOKED":
                ex_start = parse_iso8601(s["starts_at"])
                ex_end = ex_start + _minutes(s["duration_minutes"] + buf)
                if _intervals_overlap(new_start, new_end_self, ex_start, ex_end):
                    raise ApiError(errors.ERR_TRUCK_DOUBLE_BOOKED, 409,
                                   "Truck busy interval overlap")

    # Instructor double-booking (priority 13): no buffer
    for s in db.clock_sessions.values():
        if s.get("instructor_id") == instructor_id and s["status"] == "BOOKED":
            ex_start = parse_iso8601(s["starts_at"])
            ex_end = ex_start + _minutes(s["duration_minutes"])
            if _intervals_overlap(new_start, new_end_self, ex_start, ex_end):
                raise ApiError(errors.ERR_INSTRUCTOR_DOUBLE_BOOKED, 409,
                               "Instructor busy interval overlap")

    rec = stamp_create({
        "enrollment_id": eid, "truck_id": truck_id,
        "instructor_id": instructor_id, "phase": phase,
        "starts_at": iso_now(starts_at), "duration_minutes": duration,
        "status": "BOOKED",
    })
    db.clock_sessions[rec["id"]] = rec
    # reserved minutes ledgers
    SV.recompute_instructor_reserved(instr)
    touch(instr)
    if truck is not None:
        SV.recompute_truck_reserved(truck)
        touch(truck)
    SV.recompute_projected_road_hours(enr)
    return object_response(S.clock_session_out(rec), 201)


def _minutes(n):
    from datetime import timedelta
    return timedelta(minutes=n)


@app.get("/enrollments/<eid>/clock-sessions")
@require_roles("SchoolAdmin", "Registrar", "Instructor")
def list_sessions_for_enrollment(eid):
    get_enrollment(eid)
    recs = [s for s in db.clock_sessions.values() if s["enrollment_id"] == eid]
    return _list_response(recs, S.clock_session_out)


@app.get("/clock-sessions")
@require_roles("SchoolAdmin", "Registrar", "Instructor")
def list_sessions():
    truck_id = request.args.get("truck_id")
    instructor_id = request.args.get("instructor_id")
    enrollment_id = request.args.get("enrollment_id")
    recs = list(db.clock_sessions.values())
    if truck_id is not None:
        recs = [s for s in recs if s.get("truck_id") == truck_id]
    if instructor_id is not None:
        recs = [s for s in recs if s.get("instructor_id") == instructor_id]
    if enrollment_id is not None:
        recs = [s for s in recs if s["enrollment_id"] == enrollment_id]
    return _list_response(recs, S.clock_session_out)


@app.get("/clock-sessions/<sid>")
@require_roles("SchoolAdmin", "Registrar", "Instructor")
def read_session(sid):
    return object_response(S.clock_session_out(get_session(sid)))


@app.post("/clock-sessions/<sid>/complete")
@require_roles("Instructor")
def complete_session(sid):
    sess = get_session(sid)
    if sess["status"] != "BOOKED":
        raise errors.invalid_state("Session is not BOOKED")
    enr = db.enrollments.get(sess["enrollment_id"])
    if enr["status"] != "TRAINING":
        raise ApiError(errors.ERR_ENROLLMENT_NOT_TRAINING, 409,
                       "Enrollment is not in TRAINING")
    start = parse_iso8601(sess["starts_at"])
    end = start + _minutes(sess["duration_minutes"])
    if end > clock.now():
        raise ApiError(errors.ERR_SESSION_NOT_ELAPSED, 409,
                       "Session has not elapsed yet")
    sess["status"] = "COMPLETED"
    touch(sess)
    # Released from reserved (no longer BOOKED)
    if sess.get("truck_id"):
        t = db.trucks.get(sess["truck_id"])
        if t:
            SV.recompute_truck_reserved(t)
            touch(t)
    instr = db.instructors.get(sess["instructor_id"])
    if instr:
        SV.recompute_instructor_reserved(instr)
        touch(instr)
    SV.recompute_logged_hours(enr)
    SV.recompute_projected_road_hours(enr)
    SV.evaluate_test_ready_gate(enr)
    return object_response(S.clock_session_out(sess))


@app.post("/clock-sessions/<sid>/cancel")
@require_roles("Instructor", "SchoolAdmin")
def cancel_session(sid):
    sess = get_session(sid)
    from flask import g
    if sess["status"] == "BOOKED":
        # Instructor or SchoolAdmin may cancel a booked session.
        sess["status"] = "CANCELLED"
        touch(sess)
        if sess.get("truck_id"):
            t = db.trucks.get(sess["truck_id"])
            if t:
                SV.recompute_truck_reserved(t)
                touch(t)
        instr = db.instructors.get(sess["instructor_id"])
        if instr:
            SV.recompute_instructor_reserved(instr)
            touch(instr)
        enr = db.enrollments.get(sess["enrollment_id"])
        if enr:
            SV.recompute_projected_road_hours(enr)
        return object_response(S.clock_session_out(sess))
    elif sess["status"] == "COMPLETED":
        # Administrative void — SchoolAdmin only.
        if g.user_role != "SchoolAdmin":
            raise ApiError(errors.ERR_FORBIDDEN, 403,
                           "Only SchoolAdmin may void a completed session")
        enr = db.enrollments.get(sess["enrollment_id"])
        if enr and enr["status"] in ("PASSED", "COMPLETED"):
            raise ApiError(errors.ERR_SESSION_LOCKED, 409,
                           "Session locked; enrollment PASSED/COMPLETED")
        sess["status"] = "CANCELLED"
        touch(sess)
        if enr:
            SV.recompute_logged_hours(enr)
            SV.recompute_projected_road_hours(enr)
            SV.evaluate_test_ready_gate(enr)
        return object_response(S.clock_session_out(sess))
    else:
        raise errors.invalid_state("Session is terminal")


# ===========================================================================
# SkillsTest
# ===========================================================================
@app.post("/enrollments/<eid>/skills-tests")
@require_roles("Registrar")
def schedule_skills_test(eid):
    enr = get_enrollment(eid)
    body = V.get_json_body()
    # Existence (priority 3): examiner instructor + supersedes test if given
    examiner_id = V.fk_value(body, "examiner_id")
    supersedes_id = V.fk_value(body, "supersedes_test_id", required=False)
    examiner = get_instructor(examiner_id)
    if supersedes_id is not None:
        get_skills_test(supersedes_id)
    program = db.programs.get(enr["program_id"])
    # State: enrollment must be TEST_READY (priority 14)
    if enr["status"] != "TEST_READY":
        raise ApiError(errors.ERR_ENROLLMENT_NOT_TEST_READY, 409,
                       "Enrollment is not TEST_READY")
    # Segregation of duties (priority 9): examiner not instructor of a
    # COMPLETED ROAD session of this enrollment
    for s in db.clock_sessions.values():
        if (s["enrollment_id"] == eid and s["phase"] == "ROAD"
                and s["status"] == "COMPLETED"
                and s.get("instructor_id") == examiner_id):
            raise ApiError(errors.ERR_EXAMINER_CONFLICT, 409,
                           "Examiner instructed a completed road session")
    # Examiner certification (priority 10)
    if not examiner.get("examiner_certified") or \
            not _class_covers(examiner["cdl_class"], program["cdl_class"]):
        raise ApiError(errors.ERR_EXAMINER_NOT_CERTIFIED, 409,
                       "Examiner not certified for this program")
    rec = stamp_create({
        "enrollment_id": eid, "examiner_id": examiner_id,
        "supersedes_test_id": supersedes_id,
        "pre_trip_score": None, "basic_control_score": None, "road_score": None,
        "weighted_score": None, "outcome": None, "status": "SCHEDULED",
    })
    db.skills_tests[rec["id"]] = rec
    return object_response(S.skills_test_out(rec), 201)


def _class_covers(have, need):
    """CLASS_A covers CLASS_B; CLASS_B covers only CLASS_B."""
    if have == need:
        return True
    return have == "CLASS_A" and need == "CLASS_B"


@app.get("/enrollments/<eid>/skills-tests")
@require_roles("SchoolAdmin", "Registrar", "ThirdPartyExaminer")
def list_skills_for_enrollment(eid):
    get_enrollment(eid)
    recs = [t for t in db.skills_tests.values() if t["enrollment_id"] == eid]
    return _list_response(recs, S.skills_test_out)


@app.get("/skills-tests")
@require_roles("SchoolAdmin", "Registrar", "ThirdPartyExaminer")
def list_skills():
    enrollment_id = request.args.get("enrollment_id")
    examiner_id = request.args.get("examiner_id")
    supersedes_id = request.args.get("supersedes_test_id")
    recs = list(db.skills_tests.values())
    if enrollment_id is not None:
        recs = [t for t in recs if t["enrollment_id"] == enrollment_id]
    if examiner_id is not None:
        recs = [t for t in recs if t.get("examiner_id") == examiner_id]
    if supersedes_id is not None:
        recs = [t for t in recs if t.get("supersedes_test_id") == supersedes_id]
    return _list_response(recs, S.skills_test_out)


@app.get("/skills-tests/<tid>")
@require_roles("SchoolAdmin", "Registrar", "ThirdPartyExaminer")
def read_skills_test(tid):
    return object_response(S.skills_test_out(get_skills_test(tid)))


@app.post("/skills-tests/<tid>/grade")
@require_roles("ThirdPartyExaminer")
def grade_skills_test(tid):
    test = get_skills_test(tid)
    body = V.get_json_body()
    pre_trip = V.require_number(body, "pre_trip_score", minimum=0, maximum=100)
    basic = V.require_number(body, "basic_control_score", minimum=0, maximum=100)
    road = V.require_number(body, "road_score", minimum=0, maximum=100)
    if test["status"] != "SCHEDULED":
        raise errors.invalid_state("Test is not SCHEDULED")
    enr = db.enrollments.get(test["enrollment_id"])
    if enr["status"] != "TEST_READY":
        raise ApiError(errors.ERR_ENROLLMENT_NOT_TEST_READY, 409,
                       "Enrollment is not TEST_READY")
    program = db.programs.get(enr["program_id"])
    weighted = SV.compute_weighted_score(pre_trip, basic, road)
    outcome = "PASS" if weighted >= program["skills_pass_threshold"] else "FAIL"
    test["pre_trip_score"] = pre_trip
    test["basic_control_score"] = basic
    test["road_score"] = road
    test["weighted_score"] = weighted
    test["outcome"] = outcome
    test["status"] = "GRADED"
    touch(test)
    if outcome == "PASS":
        enr["status"] = "PASSED"
        touch(enr)
    return object_response(S.skills_test_out(test))


@app.post("/skills-tests/<tid>/void")
@require_roles("SchoolAdmin")
def void_skills_test(tid):
    test = get_skills_test(tid)
    if test["status"] != "SCHEDULED":
        raise errors.invalid_state("Test is not SCHEDULED")
    test["status"] = "VOIDED"
    touch(test)
    return object_response(S.skills_test_out(test))


# ===========================================================================
# SponsorshipOffer
# ===========================================================================
@app.post("/enrollments/<eid>/sponsorship-offers")
@require_roles("SchoolAdmin", "Registrar")
def extend_offer(eid):
    enr = get_enrollment(eid)
    body = V.get_json_body()
    carrier_id = V.fk_value(body, "carrier_id")
    get_carrier(carrier_id)  # FK existence (priority 3)
    rec = stamp_create({
        "enrollment_id": eid, "carrier_id": carrier_id,
        "months_served": 0, "clawback_cents": 0, "status": "OFFERED",
    })
    db.sponsorship_offers[rec["id"]] = rec
    return object_response(S.sponsorship_offer_out(rec), 201)


@app.get("/enrollments/<eid>/sponsorship-offers")
@require_roles("SchoolAdmin", "Registrar")
def list_offers_for_enrollment(eid):
    get_enrollment(eid)
    recs = [o for o in db.sponsorship_offers.values() if o["enrollment_id"] == eid]
    return _list_response(recs, S.sponsorship_offer_out)


@app.get("/sponsorship-offers")
@require_roles("SchoolAdmin", "Registrar")
def list_offers():
    enrollment_id = request.args.get("enrollment_id")
    carrier_id = request.args.get("carrier_id")
    recs = list(db.sponsorship_offers.values())
    if enrollment_id is not None:
        recs = [o for o in recs if o["enrollment_id"] == enrollment_id]
    if carrier_id is not None:
        recs = [o for o in recs if o.get("carrier_id") == carrier_id]
    return _list_response(recs, S.sponsorship_offer_out)


@app.get("/sponsorship-offers/<oid>")
@require_roles("SchoolAdmin", "Registrar")
def read_offer(oid):
    return object_response(S.sponsorship_offer_out(get_offer(oid)))


@app.post("/sponsorship-offers/<oid>/accept")
@require_roles("Registrar")
def accept_offer(oid):
    offer = get_offer(oid)
    if offer["status"] != "OFFERED":
        raise errors.invalid_state("Offer is not OFFERED")
    eid = offer["enrollment_id"]
    # Enrollment must have no other ACCEPTED offer (priority 15)
    for o in db.sponsorship_offers.values():
        if o["enrollment_id"] == eid and o["status"] == "ACCEPTED":
            raise ApiError(errors.ERR_SPONSORSHIP_CONFLICT, 409,
                           "Enrollment already has an ACCEPTED offer")
    offer["status"] = "ACCEPTED"
    touch(offer)
    enr = db.enrollments.get(eid)
    if enr:
        enr["sponsoring_carrier_id"] = offer["carrier_id"]
        touch(enr)
    return object_response(S.sponsorship_offer_out(offer))


@app.post("/sponsorship-offers/<oid>/decline")
@require_roles("Registrar")
def decline_offer(oid):
    offer = get_offer(oid)
    if offer["status"] != "OFFERED":
        raise errors.invalid_state("Offer is not OFFERED")
    offer["status"] = "DECLINED"
    touch(offer)
    return object_response(S.sponsorship_offer_out(offer))


@app.post("/sponsorship-offers/<oid>/forfeit")
@require_roles("SchoolAdmin")
def forfeit_offer_endpoint(oid):
    offer = get_offer(oid)
    if offer["status"] != "ACCEPTED":
        raise errors.invalid_state("Offer is not ACCEPTED")
    SV.forfeit_offer(offer)
    return object_response(S.sponsorship_offer_out(offer))


# ===========================================================================
# FinancePlan
# ===========================================================================
@app.post("/enrollments/<eid>/finance-plans")
@require_roles("Registrar")
def create_finance_plan(eid):
    enr = get_enrollment(eid)
    body = V.get_json_body()
    term_months = V.require_int(body, "term_months", minimum=1, maximum=36)
    expected_version = V.require_int(body, "expected_enrollment_version")
    # OCC check (priority 6) — after existence + body well-formedness
    if expected_version != enr["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_enrollment_version does not match")
    program = db.programs.get(enr["program_id"])
    tuition = program["tuition_cents"]
    sched = SV.compute_finance_schedule(tuition, term_months)
    # Supersede prior ACTIVE plan
    for fp in db.finance_plans.values():
        if fp["enrollment_id"] == eid and fp["status"] == "ACTIVE":
            fp["status"] = "SUPERSEDED"
            touch(fp)
    rec = stamp_create({
        "enrollment_id": eid, "term_months": term_months,
        "tuition_cents": tuition,
        "down_payment_cents": sched["down_payment_cents"],
        "financed_cents": sched["financed_cents"],
        "total_interest_cents": sched["total_interest_cents"],
        "installment_cents": sched["installment_cents"],
        "final_installment_cents": sched["final_installment_cents"],
        "status": "ACTIVE",
    })
    db.finance_plans[rec["id"]] = rec
    # Increment enrollment version by 1
    touch(enr)
    return object_response(S.finance_plan_out(rec), 201)


@app.get("/enrollments/<eid>/finance-plans")
@require_roles("SchoolAdmin", "Registrar")
def list_plans_for_enrollment(eid):
    get_enrollment(eid)
    recs = [p for p in db.finance_plans.values() if p["enrollment_id"] == eid]
    return _list_response(recs, S.finance_plan_out)


@app.get("/finance-plans")
@require_roles("SchoolAdmin", "Registrar")
def list_plans():
    enrollment_id = request.args.get("enrollment_id")
    recs = list(db.finance_plans.values())
    if enrollment_id is not None:
        recs = [p for p in recs if p["enrollment_id"] == enrollment_id]
    return _list_response(recs, S.finance_plan_out)


@app.get("/finance-plans/<fid>")
@require_roles("SchoolAdmin", "Registrar")
def read_plan(fid):
    return object_response(S.finance_plan_out(get_finance_plan(fid)))


# ===========================================================================
# CompletionReport
# ===========================================================================
@app.post("/enrollments/<eid>/completion-reports")
@require_roles("SchoolAdmin")
def draft_completion_report(eid):
    enr = get_enrollment(eid)
    body = V.get_json_body()
    passing_test_id = V.fk_value(body, "passing_test_id")
    get_skills_test(passing_test_id)  # FK existence (priority 3)
    rec = stamp_create({
        "enrollment_id": eid,
        "reported_classroom_hours": enr["logged_classroom_hours"],
        "reported_range_hours": enr["logged_range_hours"],
        "reported_road_hours": enr["logged_road_hours"],
        "passing_test_id": passing_test_id,
        "status": "DRAFT",
    })
    db.completion_reports[rec["id"]] = rec
    return object_response(S.completion_report_out(rec), 201)


@app.get("/enrollments/<eid>/completion-reports")
@require_roles("SchoolAdmin", "Registrar")
def list_reports_for_enrollment(eid):
    get_enrollment(eid)
    recs = [r for r in db.completion_reports.values() if r["enrollment_id"] == eid]
    return _list_response(recs, S.completion_report_out)


@app.get("/completion-reports")
@require_roles("SchoolAdmin", "Registrar")
def list_reports():
    enrollment_id = request.args.get("enrollment_id")
    passing_test_id = request.args.get("passing_test_id")
    recs = list(db.completion_reports.values())
    if enrollment_id is not None:
        recs = [r for r in recs if r["enrollment_id"] == enrollment_id]
    if passing_test_id is not None:
        recs = [r for r in recs if r.get("passing_test_id") == passing_test_id]
    return _list_response(recs, S.completion_report_out)


@app.get("/completion-reports/<rid>")
@require_roles("SchoolAdmin", "Registrar")
def read_report(rid):
    return object_response(S.completion_report_out(get_completion_report(rid)))


@app.post("/completion-reports/<rid>/transmit")
@require_roles("SchoolAdmin")
def transmit_report(rid):
    report = get_completion_report(rid)
    if report["status"] != "DRAFT":
        raise errors.invalid_state("Report is not DRAFT")
    enr = db.enrollments.get(report["enrollment_id"])
    if enr["status"] != "PASSED":
        raise ApiError(errors.ERR_ENROLLMENT_NOT_PASSED, 409,
                       "Enrollment is not PASSED")
    # passing_test_id must reference a GRADED PASS test
    test = db.skills_tests.get(report["passing_test_id"])
    if test is None or test["status"] != "GRADED" or test.get("outcome") != "PASS":
        raise errors.invalid_state("passing_test_id is not a GRADED PASS test")
    # Snapshot hour totals at transmit
    report["reported_classroom_hours"] = enr["logged_classroom_hours"]
    report["reported_range_hours"] = enr["logged_range_hours"]
    report["reported_road_hours"] = enr["logged_road_hours"]
    report["status"] = "TRANSMITTED"
    touch(report)
    enr["fmcsa_reported"] = True
    enr["status"] = "COMPLETED"
    touch(enr)
    return object_response(S.completion_report_out(report))


# ===========================================================================
# Logical clock (test-driving) — SchoolAdmin only
# ===========================================================================
@app.post("/_clock/set_current_utc")
@require_roles("SchoolAdmin")
def set_clock():
    body = V.get_json_body()
    to_iso = V.require_str(body, "to_iso8601")
    target = parse_iso8601(to_iso, "to_iso8601")
    clock.set(target)
    # Advancing past expires_on auto-expires APPROVED documents
    SV.expire_documents_past(clock.now())
    return object_response({"current_utc": iso_now(clock.now())})


@app.post("/_clock/advance_service_months")
@require_roles("SchoolAdmin")
def advance_service_months():
    body = V.get_json_body()
    offer_id = V.require_str(body, "offer_id")
    months = V.require_int(body, "months")
    offer = get_offer(offer_id)
    if offer["status"] != "ACCEPTED":
        raise errors.invalid_state("Offer is not ACCEPTED")
    offer["months_served"] += months
    touch(offer)
    SV.fulfill_if_committed(offer)
    return object_response(S.sponsorship_offer_out(offer))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
