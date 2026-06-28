"""Language School ESL API — Flask entry point.

In-memory store; starts empty on every boot (no seeding). Per-test-server
isolation restarts this process before every test.
"""
import os

from flask import Flask, request

import calculations
import errors
import middleware
import serializers as ser
import services
import validation as V
from clock import LogicalClock, iso_millis, _parse_iso
from db import Store
from response import success, list_response, error_response

app = Flask(__name__)

CLOCK = LogicalClock()
STORE = Store(CLOCK)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", str(e), 422)


# ===========================================================================
# Auth helpers
# ===========================================================================
def auth(allowed_roles, allow_anonymous=False):
    caller = middleware.authenticate(allow_anonymous=allow_anonymous)
    middleware.require_roles(caller, allowed_roles)
    return caller


# ===========================================================================
# Existence helpers (ERR_NOT_FOUND, 404)
# ===========================================================================
def get_student(sid):
    s = STORE.students.get(sid)
    if s is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Student not found")
    return s


def get_contract(cid):
    c = STORE.corporate_contracts.get(cid)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Corporate contract not found")
    return c


def get_test(tid):
    t = STORE.placement_tests.get(tid)
    if t is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Placement test not found")
    return t


def get_cohort(cid):
    c = STORE.cohorts.get(cid)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Cohort not found")
    return c


def get_enrollment(eid):
    e = STORE.enrollments.get(eid)
    if e is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Enrollment not found")
    return e


def get_addon(aid):
    a = STORE.add_ons.get(aid)
    if a is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Add-on not found")
    return a


# ===========================================================================
# Ownership helper (ERR_FORBIDDEN, 403) for entity-backed roles
# ===========================================================================
def check_student_ownership(caller, student_id):
    if caller.role == "Student" and caller.user_id != student_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Student may only act on own resources")


def check_contract_ownership(caller, contract_id):
    if caller.role == "CorporateSponsor" and caller.user_id != contract_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Sponsor may only access own contract")


# ===========================================================================
# Pagination
# ===========================================================================
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_VALIDATION_PAGINATION, "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_VALIDATION_PAGINATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.err(errors.ERR_VALIDATION_PAGINATION, "limit must be between 1 and 100")
    if offset < 0:
        raise errors.err(errors.ERR_VALIDATION_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate_and_sort(records, limit, offset, serializer):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [serializer(r) for r in window], total


# ===========================================================================
# Students
# ===========================================================================
@app.route("/students", methods=["POST"])
def create_student():
    auth({"Anonymous", "Registrar"}, allow_anonymous=True)
    data = V.body(request)
    full_name = V.require_str(data, "full_name")
    email = V.require_str(data, "email")
    is_international = V.optional_bool(data, "is_international", False)
    track = V.optional_enum(data, "track", V.TRACKS, "GENERAL")
    corporate_contract_id = V.optional_str(data, "corporate_contract_id", None)

    # FK existence (404) for sponsoring contract.
    if corporate_contract_id is not None:
        if STORE.corporate_contracts.get(corporate_contract_id) is None:
            raise errors.err(
                errors.ERR_CONTRACT_REQUIRED_FOR_SPONSOR,
                "corporate_contract_id does not reference an existing contract",
            )

    # Email uniqueness (case-insensitive), ERR_DUPLICATE_EMAIL 409.
    lowered = email.lower()
    for s in STORE.students.values():
        if s["email"].lower() == lowered:
            raise errors.err(errors.ERR_DUPLICATE_EMAIL, "Email already in use")

    rec = services.make_common(STORE)
    rec.update({
        "full_name": full_name,
        "email": email,
        "is_international": is_international,
        "corporate_contract_id": corporate_contract_id,
        "placement_level": None,
        "track": track,
        "visa_status": "NONE",
        "i20_required_weekly_hours": 0,
        "certification_status": "NONE",
        "final_progress_score": None,
    })
    STORE.students[rec["id"]] = rec
    return success(ser.student_out(rec), status=201)


@app.route("/students/<sid>", methods=["GET"])
def fetch_student(sid):
    caller = auth({"Registrar", "DSO", "Instructor", "Student"})
    s = get_student(sid)
    check_student_ownership(caller, sid)
    return success(ser.student_out(s))


@app.route("/students", methods=["GET"])
def list_students():
    auth({"Registrar", "DSO"})
    limit, offset = parse_pagination()
    contract_filter = request.args.get("corporate_contract_id")
    visa_filter = request.args.get("visa_status")
    records = list(STORE.students.values())
    if contract_filter is not None:
        records = [r for r in records if r["corporate_contract_id"] == contract_filter]
    if visa_filter is not None:
        records = [r for r in records if r["visa_status"] == visa_filter]
    items, total = paginate_and_sort(records, limit, offset, ser.student_out)
    return list_response(items, limit, offset, total)


@app.route("/students/<sid>/enrollments", methods=["GET"])
def student_enrollments(sid):
    caller = auth({"Registrar", "DSO", "Instructor", "Student"})
    get_student(sid)
    check_student_ownership(caller, sid)
    limit, offset = parse_pagination()
    records = [e for e in STORE.enrollments.values() if e["student_id"] == sid]
    items, total = paginate_and_sort(records, limit, offset, ser.enrollment_out)
    return list_response(items, limit, offset, total)


@app.route("/students/<sid>/compliance-events", methods=["GET"])
def student_compliance_events(sid):
    auth({"Registrar", "DSO"})
    get_student(sid)
    limit, offset = parse_pagination()
    records = [c for c in STORE.compliance_events.values() if c["student_id"] == sid]
    items, total = paginate_and_sort(records, limit, offset, ser.compliance_event_out)
    return list_response(items, limit, offset, total)


@app.route("/students/<sid>/add-ons", methods=["GET"])
def student_addons(sid):
    caller = auth({"Registrar", "Student"})
    get_student(sid)
    check_student_ownership(caller, sid)
    limit, offset = parse_pagination()
    records = [a for a in STORE.add_ons.values() if a["student_id"] == sid]
    items, total = paginate_and_sort(records, limit, offset, ser.addon_out)
    return list_response(items, limit, offset, total)


@app.route("/students/<sid>/placement-tests", methods=["GET"])
def student_placement_tests(sid):
    caller = auth({"Registrar", "Instructor", "Student"})
    get_student(sid)
    check_student_ownership(caller, sid)
    limit, offset = parse_pagination()
    records = [t for t in STORE.placement_tests.values() if t["student_id"] == sid]
    items, total = paginate_and_sort(records, limit, offset, ser.placement_test_out)
    return list_response(items, limit, offset, total)


# ---- Visa lifecycle (DSO) ----
@app.route("/students/<sid>/issue-i20", methods=["POST"])
def issue_i20(sid):
    auth({"DSO"})
    s = get_student(sid)
    data = V.body(request)
    reason = V.optional_str(data, "reason", None)
    # State precondition (PRD §3.8): is_international true, visa_status == NONE.
    if not s["is_international"] or s["visa_status"] != "NONE":
        raise errors.err(errors.ERR_INVALID_STATE, "Cannot issue I-20 in current state")
    prior = s["visa_status"]
    s["visa_status"] = "INITIAL"
    s["i20_required_weekly_hours"] = 18
    services._touch(STORE, s)
    services.append_compliance_event(STORE, s, "I20_ISSUED", prior, "INITIAL", reason)
    return success(ser.student_out(s))


@app.route("/students/<sid>/activate-status", methods=["POST"])
def activate_status(sid):
    auth({"DSO"})
    s = get_student(sid)
    data = V.body(request)
    reason = V.optional_str(data, "reason", None)
    if s["visa_status"] != "INITIAL":
        raise errors.err(errors.ERR_INVALID_STATE, "Visa status must be INITIAL to activate")
    if not services.meets_full_course(STORE, s):
        raise errors.err(errors.ERR_NOT_FULL_COURSE_OF_STUDY, "Not a full course of study")
    prior = s["visa_status"]
    s["visa_status"] = "ACTIVE"
    services._touch(STORE, s)
    services.append_compliance_event(STORE, s, "STATUS_ACTIVATED", prior, "ACTIVE", reason)
    return success(ser.student_out(s))


@app.route("/students/<sid>/place-probation", methods=["POST"])
def place_probation(sid):
    auth({"DSO"})
    s = get_student(sid)
    data = V.body(request)
    reason = V.optional_str(data, "reason", None)
    if s["visa_status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Visa status must be ACTIVE to place on probation")
    prior = s["visa_status"]
    s["visa_status"] = "PROBATION"
    services._touch(STORE, s)
    services.append_compliance_event(STORE, s, "PROBATION_PLACED", prior, "PROBATION", reason)
    return success(ser.student_out(s))


@app.route("/students/<sid>/clear-probation", methods=["POST"])
def clear_probation(sid):
    auth({"DSO"})
    s = get_student(sid)
    data = V.body(request)
    reason = V.optional_str(data, "reason", None)
    if s["visa_status"] != "PROBATION":
        raise errors.err(errors.ERR_INVALID_STATE, "Visa status must be PROBATION to clear")
    if not services.meets_full_course(STORE, s):
        raise errors.err(errors.ERR_NOT_FULL_COURSE_OF_STUDY, "Not a full course of study")
    prior = s["visa_status"]
    s["visa_status"] = "ACTIVE"
    services._touch(STORE, s)
    services.append_compliance_event(STORE, s, "PROBATION_CLEARED", prior, "ACTIVE", reason)
    return success(ser.student_out(s))


@app.route("/students/<sid>/terminate-status", methods=["POST"])
def terminate_status(sid):
    auth({"DSO"})
    s = get_student(sid)
    data = V.body(request)
    reason = V.optional_str(data, "reason", None)
    if s["visa_status"] != "PROBATION":
        raise errors.err(errors.ERR_INVALID_STATE, "Visa status must be PROBATION to terminate")
    prior = s["visa_status"]
    s["visa_status"] = "TERMINATED"
    services._touch(STORE, s)
    services.append_compliance_event(STORE, s, "I20_TERMINATED", prior, "TERMINATED", reason)
    # Cascade: terminate every ENROLLED enrollment with VISA_NONCOMPLIANCE.
    enrolled = [
        e for e in STORE.enrollments.values()
        if e["student_id"] == sid and e["status"] == "ENROLLED"
    ]
    enrolled.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for e in enrolled:
        services.terminate_enrollment(STORE, e, "VISA_NONCOMPLIANCE", cascade_visa=False)
    # Void certification if PROVISIONAL or CERTIFIED.
    if s["certification_status"] in ("PROVISIONAL", "CERTIFIED"):
        s["certification_status"] = "VOIDED"
        services._touch(STORE, s)
    return success(ser.student_out(s))


# ===========================================================================
# Placement Tests
# ===========================================================================
@app.route("/placement-tests", methods=["POST"])
def create_placement_test():
    caller = auth({"Anonymous", "Registrar", "Student"}, allow_anonymous=True)
    data = V.body(request)
    student_id = V.require_str(data, "student_id")
    # Ownership: a Student may only register their own test.
    check_student_ownership(caller, student_id)
    get_student(student_id)
    rec = services.make_common(STORE)
    rec.update({
        "student_id": student_id,
        "raw_score": None,
        "assigned_level": None,
        "status": "REGISTERED",
    })
    STORE.placement_tests[rec["id"]] = rec
    return success(ser.placement_test_out(rec), status=201)


@app.route("/placement-tests/<tid>", methods=["GET"])
def fetch_placement_test(tid):
    caller = auth({"Registrar", "Instructor", "Student"})
    t = get_test(tid)
    check_student_ownership(caller, t["student_id"])
    return success(ser.placement_test_out(t))


@app.route("/placement-tests/<tid>/score", methods=["POST"])
def score_placement_test(tid):
    auth({"Instructor"})
    t = get_test(tid)
    # State gate before field validation per pipeline (state=409 precedes business rules).
    if t["status"] != "REGISTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Test must be REGISTERED to score")
    data = V.body(request)
    raw_score = V.require_int(data, "raw_score", minimum=0, maximum=100)
    level = calculations.placement_band(raw_score)
    t["raw_score"] = raw_score
    t["assigned_level"] = level
    t["status"] = "SCORED"
    t["recorded_at"] = iso_millis(STORE.clock.now())
    services._touch(STORE, t)
    # Propagate to student.placement_level: latest scored test wins (greatest
    # recorded_at, tie-break earlier created_at ASC).
    _recompute_placement_level(t["student_id"])
    return success(ser.placement_test_out(t))


def _recompute_placement_level(student_id):
    student = STORE.students.get(student_id)
    if student is None:
        return
    scored = [
        t for t in STORE.placement_tests.values()
        if t["student_id"] == student_id and t["status"] == "SCORED"
    ]
    if not scored:
        return
    # latest = greatest recorded_at; tie-break earlier created_at (then _seq) ASC.
    max_recorded = max(t["recorded_at"] for t in scored)
    tied = [t for t in scored if t["recorded_at"] == max_recorded]
    latest = min(tied, key=lambda t: (t["created_at"], t["_seq"]))
    student["placement_level"] = latest["assigned_level"]
    services._touch(STORE, student)


@app.route("/placement-tests/<tid>/void", methods=["POST"])
def void_placement_test(tid):
    auth({"Registrar"})
    t = get_test(tid)
    if t["status"] != "REGISTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Test must be REGISTERED to void")
    t["status"] = "VOIDED"
    services._touch(STORE, t)
    return success(ser.placement_test_out(t))


# ===========================================================================
# Cohorts
# ===========================================================================
@app.route("/cohorts", methods=["POST"])
def create_cohort():
    auth({"Registrar"})
    data = V.body(request)
    name = V.require_str(data, "name")
    level = V.require_enum(data, "level", V.LEVELS)
    track = V.require_enum(data, "track", V.TRACKS)
    capacity = V.require_int(data, "capacity", minimum=1)
    weekly_hours = V.require_int(data, "weekly_hours", minimum=1)
    term_start = V.require_datetime(data, "term_start")
    term_end = V.require_datetime(data, "term_end")
    total_sessions = V.require_int(data, "total_sessions", minimum=1)
    base_tuition_cents = V.require_int(data, "base_tuition_cents", minimum=0)
    schedule_block = V.require_enum(data, "schedule_block", V.SCHEDULE_BLOCKS)
    if _parse_iso(term_end) <= _parse_iso(term_start):
        raise V.invalid("term_end must be strictly after term_start")

    rec = services.make_common(STORE)
    rec.update({
        "name": name,
        "level": level,
        "track": track,
        "capacity": capacity,
        "weekly_hours": weekly_hours,
        "term_start": term_start,
        "term_end": term_end,
        "total_sessions": total_sessions,
        "base_tuition_cents": base_tuition_cents,
        "seats_taken": 0,
        "schedule_block": schedule_block,
        "status": "OPEN",
    })
    STORE.cohorts[rec["id"]] = rec
    return success(ser.cohort_out(rec), status=201)


@app.route("/cohorts/<cid>", methods=["GET"])
def fetch_cohort(cid):
    auth({"Registrar", "DSO", "Instructor", "Student"})
    c = get_cohort(cid)
    return success(ser.cohort_out(c))


@app.route("/cohorts", methods=["GET"])
def list_cohorts():
    auth({"Registrar", "DSO", "Instructor", "Student"})
    limit, offset = parse_pagination()
    level = request.args.get("level")
    track = request.args.get("track")
    status = request.args.get("status")
    records = list(STORE.cohorts.values())
    if level is not None:
        records = [r for r in records if r["level"] == level]
    if track is not None:
        records = [r for r in records if r["track"] == track]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, total = paginate_and_sort(records, limit, offset, ser.cohort_out)
    return list_response(items, limit, offset, total)


@app.route("/cohorts/<cid>/enrollments", methods=["GET"])
def cohort_enrollments(cid):
    auth({"Registrar", "DSO", "Instructor"})
    get_cohort(cid)
    limit, offset = parse_pagination()
    records = [e for e in STORE.enrollments.values() if e["cohort_id"] == cid]
    items, total = paginate_and_sort(records, limit, offset, ser.enrollment_out)
    return list_response(items, limit, offset, total)


# ===========================================================================
# Enrollments
# ===========================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    auth({"Registrar"})
    data = V.body(request)
    student_id = V.require_str(data, "student_id")
    cohort_id = V.require_str(data, "cohort_id")
    get_student(student_id)
    get_cohort(cohort_id)
    rec = services.make_common(STORE)
    rec.update({
        "student_id": student_id,
        "cohort_id": cohort_id,
        "status": "PLACEMENT_PENDING",
        "enrolled_at": None,
        "sessions_attended": 0,
        "sessions_elapsed": 0,
        "attendance_rate": 1.0,
        "tuition_invoice_cents": 0,
        "refund_cents": 0,
        "completion_score": None,
        "termination_reason": None,
    })
    STORE.enrollments[rec["id"]] = rec
    return success(ser.enrollment_out(rec), status=201)


@app.route("/enrollments/<eid>", methods=["GET"])
def fetch_enrollment(eid):
    caller = auth({"Registrar", "DSO", "Instructor", "Student"})
    e = get_enrollment(eid)
    check_student_ownership(caller, e["student_id"])
    return success(ser.enrollment_out(e))


@app.route("/enrollments/<eid>/confirm", methods=["POST"])
def confirm_enrollment(eid):
    auth({"Registrar"})
    e = get_enrollment(eid)
    # State gate (409) before business rules.
    if e["status"] != "PLACEMENT_PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Enrollment must be PLACEMENT_PENDING to confirm")

    data = V.body(request)
    # require_seat is optional. expected_cohort_version is read here but its
    # field-level validation is deferred to the OCC step, because PRD §3.4 pins
    # field validation (ERR_INVALID_REQUEST) as the very last gate.
    require_seat = V.optional_bool(data, "require_seat", False)

    student = STORE.students.get(e["student_id"])
    cohort = STORE.cohorts.get(e["cohort_id"])

    # Confirm-specific ordering (PRD §3.4):
    #   placement -> visa -> schedule -> contract-seat -> cohort-full -> OCC -> field.
    # 1. placement gate (applies to both ENROLLED and WAITLISTED branches)
    if student["placement_level"] != cohort["level"] or student["track"] != cohort["track"]:
        raise errors.err(errors.ERR_PLACEMENT_MISMATCH, "Placement level/track mismatch")

    has_seat = cohort["seats_taken"] < cohort["capacity"] and cohort["status"] == "OPEN"

    if has_seat:
        # ENROLLED branch enforces the compliance + capacity guards in pinned order.
        # 2. F-1 visa gate
        if student["is_international"] and student["visa_status"] not in ("INITIAL", "ACTIVE"):
            raise errors.err(errors.ERR_VISA_NONCOMPLIANT, "Student visa status not compliant")
        # 3. schedule-conflict gate
        if _has_schedule_conflict(student, cohort, e):
            raise errors.err(errors.ERR_SCHEDULE_CONFLICT, "Schedule conflict with another enrollment")
        # 4. corporate-contract seat gate (sponsored)
        if student["corporate_contract_id"]:
            contract = STORE.corporate_contracts.get(student["corporate_contract_id"])
            if contract is None or contract["status"] in ("EXHAUSTED", "CLOSED") \
                    or contract["seats_consumed"] >= contract["contracted_seats"]:
                raise errors.err(errors.ERR_CONTRACT_SEATS_EXHAUSTED, "Contract seats exhausted")
        # 6. OCC version check (last business gate); 7. field validation last of all.
        expected_version = V.require_int(data, "expected_cohort_version")
        if expected_version != cohort["version"]:
            raise errors.err(errors.ERR_STALE_COHORT_VERSION, "Stale cohort version")
        # enter_enrolled -> acquire_seats touches the cohort once: that single
        # version bump IS the confirm's "increment cohort version by 1".
        services.enter_enrolled(STORE, e, student, cohort)
        return success(ser.enrollment_out(e))
    else:
        # No free seat.
        # 5. cohort-full gate: with require_seat, full is an error not a waitlist.
        if require_seat:
            raise errors.err(errors.ERR_COHORT_FULL, "Cohort is full")
        # 6. OCC version check (last business gate) — applies to WAITLISTED branch too.
        expected_version = V.require_int(data, "expected_cohort_version")
        if expected_version != cohort["version"]:
            raise errors.err(errors.ERR_STALE_COHORT_VERSION, "Stale cohort version")
        e["status"] = "WAITLISTED"
        services._touch(STORE, e)
        # No seat touched on this branch, so bump the cohort version once explicitly.
        services._touch(STORE, cohort)
        return success(ser.enrollment_out(e))


def _has_schedule_conflict(student, target_cohort, this_enrollment):
    """PRD §3.4: another ENROLLED enrollment, same schedule_block, closed-interval
    overlap on [term_start, term_end]."""
    t_start = _parse_iso(target_cohort["term_start"])
    t_end = _parse_iso(target_cohort["term_end"])
    for e in STORE.enrollments.values():
        if e["id"] == this_enrollment["id"]:
            continue
        if e["student_id"] != student["id"] or e["status"] != "ENROLLED":
            continue
        other = STORE.cohorts.get(e["cohort_id"])
        if other is None or other["schedule_block"] != target_cohort["schedule_block"]:
            continue
        o_start = _parse_iso(other["term_start"])
        o_end = _parse_iso(other["term_end"])
        # closed-interval overlap: earlier end on or after later start.
        if t_start <= o_end and o_start <= t_end:
            return True
    return False


@app.route("/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    auth({"Registrar"})
    e = get_enrollment(eid)
    if e["status"] != "ENROLLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Enrollment must be ENROLLED to withdraw")
    student = STORE.students.get(e["student_id"])
    cohort = STORE.cohorts.get(e["cohort_id"])

    # Refund off the pinned net tuition_invoice_cents.
    e["refund_cents"] = calculations.withdrawal_refund(
        e["tuition_invoice_cents"], STORE.clock.now(), _parse_iso(cohort["term_start"])
    )
    e["status"] = "WITHDRAWN"
    services._touch(STORE, e)

    services.release_seats(STORE, e, student, cohort)
    services.promote_waitlist(STORE, cohort)

    # Visa cascade: international student now with zero ENROLLED -> PROBATION.
    if student["is_international"]:
        remaining = [
            x for x in STORE.enrollments.values()
            if x["student_id"] == student["id"] and x["status"] == "ENROLLED"
        ]
        if len(remaining) == 0 and student["visa_status"] == "ACTIVE":
            prior = student["visa_status"]
            student["visa_status"] = "PROBATION"
            services._touch(STORE, student)
            services.append_compliance_event(
                STORE, student, "PROBATION_PLACED", prior, "PROBATION", None
            )
    return success(ser.enrollment_out(e))


@app.route("/enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment_route(eid):
    auth({"DSO"})
    e = get_enrollment(eid)
    if e["status"] != "ENROLLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Enrollment must be ENROLLED to terminate")
    data = V.body(request)
    reason = data.get("termination_reason")
    if reason not in V.TERMINATION_REASONS:
        raise errors.err(
            errors.ERR_INVALID_TERMINATION_REASON,
            "termination_reason must be one of VISA_NONCOMPLIANCE, ATTENDANCE_FAILURE, CONTRACT_REVOKED",
        )
    services.terminate_enrollment(STORE, e, reason, cascade_visa=True)
    return success(ser.enrollment_out(e))


@app.route("/enrollments/<eid>/complete", methods=["POST"])
def complete_enrollment(eid):
    auth({"Registrar"})
    e = get_enrollment(eid)
    if e["status"] != "ENROLLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Enrollment must be ENROLLED to complete")
    student = STORE.students.get(e["student_id"])
    cohort = STORE.cohorts.get(e["cohort_id"])

    # Completion gate: clock >= term_end, attendance_rate >= 0.70, >=1 progress report.
    now = STORE.clock.now()
    reports = [p for p in STORE.progress_reports.values() if p["enrollment_id"] == e["id"]]
    if now < _parse_iso(cohort["term_end"]) \
            or e["attendance_rate"] < calculations.MIN_PASS_ATTENDANCE \
            or len(reports) == 0:
        raise errors.err(errors.ERR_COMPLETION_REQUIREMENTS_UNMET, "Completion requirements unmet")

    # completion_score from latest progress report: greatest assessed_at,
    # tie-break earlier created_at (then _seq) ASC.
    max_assessed = max(p["assessed_at"] for p in reports)
    tied = [p for p in reports if p["assessed_at"] == max_assessed]
    latest = min(tied, key=lambda p: (p["created_at"], p["_seq"]))
    e["completion_score"] = calculations.completion_score(latest, e["attendance_rate"])
    e["status"] = "COMPLETED"
    services._touch(STORE, e)

    services.release_seats(STORE, e, student, cohort)
    services.promote_waitlist(STORE, cohort)
    services.recompute_certification(STORE, student)
    return success(ser.enrollment_out(e))


# ===========================================================================
# Attendance
# ===========================================================================
@app.route("/attendance", methods=["POST"])
def create_attendance():
    auth({"Instructor"})
    data = V.body(request)
    enrollment_id = V.require_str(data, "enrollment_id")
    session_index = V.require_int(data, "session_index")
    status = V.require_enum(data, "status", V.ATTENDANCE_STATUSES)
    e = get_enrollment(enrollment_id)
    cohort = STORE.cohorts.get(e["cohort_id"])

    # Uniqueness + range (ERR_DUPLICATE_SESSION, 409).
    if session_index < 1 or session_index > cohort["total_sessions"]:
        raise errors.err(errors.ERR_DUPLICATE_SESSION, "session_index out of range")
    for a in STORE.attendance_records.values():
        if a["enrollment_id"] == enrollment_id and a["session_index"] == session_index:
            raise errors.err(errors.ERR_DUPLICATE_SESSION, "session_index already recorded")

    rec = services.make_append_only(STORE)
    rec.update({
        "enrollment_id": enrollment_id,
        "session_index": session_index,
        "status": status,
        "recorded_at": iso_millis(STORE.clock.now()),
    })
    STORE.attendance_records[rec["id"]] = rec
    services.recompute_attendance(STORE, e)
    services._touch(STORE, e)
    return success(ser.attendance_out(rec), status=201)


@app.route("/enrollments/<eid>/attendance", methods=["GET"])
def enrollment_attendance(eid):
    caller = auth({"Registrar", "DSO", "Instructor", "Student"})
    e = get_enrollment(eid)
    check_student_ownership(caller, e["student_id"])
    limit, offset = parse_pagination()
    records = [a for a in STORE.attendance_records.values() if a["enrollment_id"] == eid]
    items, total = paginate_and_sort(records, limit, offset, ser.attendance_out)
    return list_response(items, limit, offset, total)


# ===========================================================================
# Progress Reports
# ===========================================================================
@app.route("/progress-reports", methods=["POST"])
def create_progress_report():
    auth({"Instructor"})
    data = V.body(request)
    enrollment_id = V.require_str(data, "enrollment_id")
    speaking = V.require_int(data, "speaking", minimum=0, maximum=100)
    listening = V.require_int(data, "listening", minimum=0, maximum=100)
    reading = V.require_int(data, "reading", minimum=0, maximum=100)
    writing = V.require_int(data, "writing", minimum=0, maximum=100)
    get_enrollment(enrollment_id)
    rec = services.make_common(STORE)
    rec.update({
        "enrollment_id": enrollment_id,
        "speaking": speaking,
        "listening": listening,
        "reading": reading,
        "writing": writing,
        "assessed_at": iso_millis(STORE.clock.now()),
    })
    STORE.progress_reports[rec["id"]] = rec
    return success(ser.progress_out(rec), status=201)


@app.route("/enrollments/<eid>/progress-reports", methods=["GET"])
def enrollment_progress_reports(eid):
    caller = auth({"Registrar", "DSO", "Instructor", "Student"})
    e = get_enrollment(eid)
    check_student_ownership(caller, e["student_id"])
    limit, offset = parse_pagination()
    records = [p for p in STORE.progress_reports.values() if p["enrollment_id"] == eid]
    items, total = paginate_and_sort(records, limit, offset, ser.progress_out)
    return list_response(items, limit, offset, total)


# ===========================================================================
# Add-ons
# ===========================================================================
@app.route("/add-ons", methods=["POST"])
def create_addon():
    caller = auth({"Registrar", "Student"})
    data = V.body(request)
    student_id = V.require_str(data, "student_id")
    enrollment_id = V.require_str(data, "enrollment_id")
    add_on_type = V.require_enum(data, "add_on_type", V.ADD_ON_TYPES)
    units = V.require_int(data, "units", minimum=1)
    # Ownership: Student may only create their own add-ons.
    check_student_ownership(caller, student_id)
    get_student(student_id)
    e = get_enrollment(enrollment_id)
    # Enrollment must belong to the named student.
    if e["student_id"] != student_id:
        raise errors.err(errors.ERR_ADDON_ENROLLMENT_MISMATCH, "Enrollment does not belong to student")

    fee = calculations.addon_fee(add_on_type, units)
    rec = services.make_common(STORE)
    rec.update({
        "student_id": student_id,
        "add_on_type": add_on_type,
        "enrollment_id": enrollment_id,
        "units": units,
        "fee_cents": fee,
        "status": "ACTIVE",
    })
    STORE.add_ons[rec["id"]] = rec
    return success(ser.addon_out(rec), status=201)


@app.route("/add-ons/<aid>", methods=["GET"])
def fetch_addon(aid):
    caller = auth({"Registrar", "Student"})
    a = get_addon(aid)
    check_student_ownership(caller, a["student_id"])
    return success(ser.addon_out(a))


@app.route("/enrollments/<eid>/add-ons", methods=["GET"])
def enrollment_addons(eid):
    caller = auth({"Registrar", "DSO", "Student"})
    e = get_enrollment(eid)
    check_student_ownership(caller, e["student_id"])
    limit, offset = parse_pagination()
    records = [a for a in STORE.add_ons.values() if a["enrollment_id"] == eid]
    items, total = paginate_and_sort(records, limit, offset, ser.addon_out)
    return list_response(items, limit, offset, total)


@app.route("/add-ons/<aid>/cancel", methods=["POST"])
def cancel_addon(aid):
    caller = auth({"Student"})
    a = get_addon(aid)
    check_student_ownership(caller, a["student_id"])
    # State preconditions: add-on ACTIVE and parent enrollment not terminal.
    if a["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Add-on must be ACTIVE to cancel")
    enrollment = STORE.enrollments.get(a["enrollment_id"])
    if enrollment is None or enrollment["status"] not in ("PLACEMENT_PENDING", "ENROLLED", "WAITLISTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Parent enrollment is terminal")
    a["status"] = "CANCELLED"
    services._touch(STORE, a)
    return success(ser.addon_out(a))


# ===========================================================================
# Corporate Contracts
# ===========================================================================
@app.route("/corporate-contracts", methods=["POST"])
def create_contract():
    auth({"Registrar"})
    data = V.body(request)
    company_name = V.require_str(data, "company_name")
    contracted_seats = V.require_int(data, "contracted_seats", minimum=1)
    discount_tier = V.optional_enum(data, "discount_tier", V.DISCOUNT_TIERS, "BRONZE")
    rec = services.make_common(STORE)
    rec.update({
        "company_name": company_name,
        "contracted_seats": contracted_seats,
        "seats_consumed": 0,
        "discount_tier": discount_tier,
        "status": "ACTIVE",
    })
    STORE.corporate_contracts[rec["id"]] = rec
    return success(ser.contract_out(rec), status=201)


@app.route("/corporate-contracts/<cid>", methods=["GET"])
def fetch_contract(cid):
    caller = auth({"Registrar", "CorporateSponsor"})
    c = get_contract(cid)
    check_contract_ownership(caller, cid)
    return success(ser.contract_out(c))


@app.route("/corporate-contracts/<cid>/students", methods=["GET"])
def contract_students(cid):
    caller = auth({"Registrar", "CorporateSponsor"})
    get_contract(cid)
    check_contract_ownership(caller, cid)
    limit, offset = parse_pagination()
    records = [s for s in STORE.students.values() if s["corporate_contract_id"] == cid]
    items, total = paginate_and_sort(records, limit, offset, ser.student_out)
    return list_response(items, limit, offset, total)


@app.route("/corporate-contracts/<cid>/close", methods=["POST"])
def close_contract(cid):
    auth({"Registrar"})
    c = get_contract(cid)
    if c["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Contract must be ACTIVE or EXHAUSTED to close")
    data = V.body(request)
    expected_version = V.require_int(data, "expected_contract_version")
    if expected_version != c["version"]:
        raise errors.err(errors.ERR_STALE_CONTRACT_VERSION, "Stale contract version")

    # Cascade: terminate every sponsored ENROLLED enrollment (CONTRACT_REVOKED).
    sponsored_students = {
        s["id"] for s in STORE.students.values() if s["corporate_contract_id"] == cid
    }
    to_terminate = [
        e for e in STORE.enrollments.values()
        if e["student_id"] in sponsored_students and e["status"] == "ENROLLED"
    ]
    to_terminate.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for e in to_terminate:
        services.terminate_enrollment(STORE, e, "CONTRACT_REVOKED", cascade_visa=False)

    c["status"] = "CLOSED"
    services._touch(STORE, c)
    return success(ser.contract_out(c))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"Registrar", "DSO"})
    data = V.body(request)
    to_iso = data.get("to_iso8601")
    if not isinstance(to_iso, str) or to_iso == "":
        raise V.invalid("to_iso8601 is required and must be an ISO 8601 string")
    try:
        STORE.clock.set_iso(to_iso)
    except Exception:
        raise V.invalid("to_iso8601 must be a valid ISO 8601 datetime")
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
