"""Reference data: buildings, terms, staff, students -- and the logical clock."""
import datetime

from flask import Blueprint

import auth
import calc
import cascade
import envelope
import serial
import shape
import store
from errors import ApiError
from routes_reads import fetch

bp = Blueprint("ref", __name__)


# ------------------------------------------------------------------ schools
@bp.post("/rostering/schools")
def create_school():
    auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    record = {
        "name": shape.req_str(body, "name", 1, 120),
        "sis_school_id": shape.req_str(body, "sis_school_id", 1, 32),
        "building_code": shape.req_str(body, "building_code", 1, 16),
        "grade_band": shape.req_enum(body, "grade_band", shape.GRADE_BANDS),
        "status": "ACTIVE",
        "min_password_length": shape.opt_int(body, "min_password_length", 8, 6, 64),
        "password_requires_mixed_case": shape.opt_bool(
            body, "password_requires_mixed_case", True),
        "password_max_age_days": shape.opt_int(
            body, "password_max_age_days", 180, 30, 365),
        "password_lockout_threshold": shape.opt_int(
            body, "password_lockout_threshold", 5, 3, 20),
        "temp_password_ttl_hours": shape.opt_int(
            body, "temp_password_ttl_hours", 72, 1, 336),
        "enrolled_student_count": 0,
    }
    store.stamp_new(record)
    store.schools[record["id"]] = record
    return envelope.created(serial.school(record))


@bp.patch("/rostering/schools/<school_id>")
def amend_school(school_id):
    auth.require(auth.ROSTER_OPERATOR, auth.DATA_GOVERNANCE_OFFICER)
    school = fetch(store.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
    body = shape.body()
    status = shape.opt_enum(body, "status", ["ACTIVE", "CLOSED"])
    updates = {}
    if status is not None:
        updates["status"] = status
    for field, low, high in (("min_password_length", 6, 64),
                             ("password_max_age_days", 30, 365),
                             ("password_lockout_threshold", 3, 20),
                             ("temp_password_ttl_hours", 1, 336)):
        value = shape.opt_int(body, field, None, low, high)
        if value is not None:
            updates[field] = value
    mixed = shape.opt_bool(body, "password_requires_mixed_case", None)
    if mixed is not None:
        updates["password_requires_mixed_case"] = mixed
    school.update(updates)
    store.touch(school)
    return envelope.ok(serial.school(school))


# -------------------------------------------------------------------- terms
@bp.post("/rostering/terms")
def create_term():
    auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    name = shape.req_str(body, "name", 1)
    school_year = shape.req_int(body, "school_year", 2000, 2100)
    start = shape.req_date(body, "start_date")
    end = shape.req_date(body, "end_date")
    cutoff = shape.req_date(body, "add_drop_cutoff_date")
    instructional_days = shape.req_int(body, "instructional_days", 1, 250)
    retention = shape.opt_int(body, "archive_retention_days", 90, 0, 730)
    if not (start < end and start <= cutoff <= end):
        raise ApiError("ERR_TERM_DATE_ORDER",
                       "start_date <= add_drop_cutoff_date <= end_date is required.")
    record = {
        "name": name,
        "school_year": school_year,
        "start_date": store.fmt_date(start),
        "end_date": store.fmt_date(end),
        "add_drop_cutoff_date": store.fmt_date(cutoff),
        "instructional_days": instructional_days,
        "archive_retention_days": retention,
        "state": "PLANNED",
        "archived_access_expires_at": None,
    }
    store.stamp_new(record)
    store.terms[record["id"]] = record
    return envelope.created(serial.term(record))


@bp.post("/rostering/terms/<term_id>/activate")
def activate_term(term_id):
    auth.require(auth.ROSTER_OPERATOR)
    term = fetch(store.terms, term_id, "ERR_TERM_NOT_FOUND")
    if term.get("state") != "PLANNED":
        raise ApiError("ERR_TERM_NOT_ACTIVE", "Only a PLANNED term can be activated.")
    if store.clock_date() > calc.as_date(term["end_date"]):
        raise ApiError("ERR_TERM_WINDOW_CLOSED", "The term has already ended.")
    term["state"] = "ACTIVE"
    store.touch(term)
    return envelope.ok(serial.term(term))


@bp.post("/rostering/terms/<term_id>/rollover")
def rollover_term(term_id):
    auth.require(auth.DATA_GOVERNANCE_OFFICER)
    term = fetch(store.terms, term_id, "ERR_TERM_NOT_FOUND")
    if term.get("state") != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE", "Only an ACTIVE term can be rolled over.")
    end_date = calc.as_date(term["end_date"])
    if store.clock_date() < end_date:
        raise ApiError("ERR_TERM_WINDOW_CLOSED", "The term has not ended yet.")

    deadline = calc.add_days(end_date, term.get("archive_retention_days") or 0)
    term["archived_access_expires_at"] = store.fmt_instant(
        datetime.datetime(deadline.year, deadline.month, deadline.day))

    # hop 2: ACTIVE sections of this term are archived; CANCELLED are untouched.
    archived = []
    for section in store.sorted_records(store.sections):
        if section.get("term_id") == term_id and section.get("status") == "ACTIVE":
            section["status"] = "ARCHIVED"
            store.touch(section)
            archived.append(section)
    archived_ids = set(s["id"] for s in archived)

    # hop 3: live enrollments of those sections are dropped at the term end.
    touched_students = []
    for enrollment in store.sorted_records(store.enrollments):
        if enrollment.get("section_id") not in archived_ids:
            continue
        if enrollment.get("roster_status") not in ("PENDING_ADD", "ACTIVE", "PENDING_DROP"):
            continue
        enrollment["roster_status"] = "DROPPED"
        enrollment["drop_effective_date"] = term["end_date"]
        store.touch(enrollment)
        student = store.students.get(enrollment.get("student_id"))
        if student is not None and student not in touched_students:
            touched_students.append(student)
    for section in archived:
        cascade.recompute_section_count(section)
    for student in touched_students:
        cascade.recompute_student_count(student)

    # hop 4: seats go back and identities are parked, not destroyed.
    affected = set()
    for student in touched_students:
        cascade.release_student_seats(student, store.clock_date(),
                                     identity="SUSPENDED", term_id=term_id,
                                     aggregate=affected)
    for vendor_id in sorted(affected):
        cascade.recompute_vendor(store.vendor_apps.get(vendor_id), bump_version=True)

    term["state"] = "ROLLED_OVER"
    store.touch(term)
    return envelope.ok(serial.term(term))


# ----------------------------------------------------------------- teachers
@bp.post("/rostering/teachers")
def create_teacher():
    auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    school_id = shape.req_id(body, "school_id")
    sis_staff_id = shape.req_str(body, "sis_staff_id", 1, 32)
    full_name = shape.req_str(body, "full_name", 1, 120)
    email = shape.req_str(body, "email", 3, 160)
    if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        shape.bad("email must contain exactly one at-sign.")
    school = fetch(store.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
    if school.get("status") != "ACTIVE":
        raise ApiError("ERR_SCHOOL_CLOSED", "The building is CLOSED.")
    for other in store.teachers.values():
        if other.get("sis_staff_id") == sis_staff_id:
            raise ApiError("ERR_DUPLICATE_SIS_ID",
                           "sis_staff_id is already registered.")
    record = {
        "school_id": school_id,
        "sis_staff_id": sis_staff_id,
        "full_name": full_name,
        "email": email,
        "employment_status": "ACTIVE",
        "separation_effective_date": None,
    }
    store.stamp_new(record)
    store.teachers[record["id"]] = record
    return envelope.created(serial.teacher(record))


@bp.post("/rostering/teachers/<teacher_id>/separate")
def separate_teacher(teacher_id):
    auth.require(auth.DATA_GOVERNANCE_OFFICER)
    teacher = fetch(store.teachers, teacher_id, "ERR_TEACHER_NOT_FOUND")
    body = shape.body()
    effective = shape.req_date(body, "separation_effective_date")
    if teacher.get("employment_status") != "ACTIVE":
        raise ApiError("ERR_TEACHER_SEPARATED", "The teacher is already SEPARATED.")

    teacher["employment_status"] = "SEPARATED"
    teacher["separation_effective_date"] = store.fmt_date(effective)
    store.touch(teacher)

    # level 1: every section this teacher was the teacher of record for.
    orphaned = []
    for section in store.sorted_records(store.sections):
        if section.get("primary_teacher_id") == teacher_id:
            if section.get("roster_health") != "UNMATCHED_TEACHER":
                section["roster_health"] = "UNMATCHED_TEACHER"
                store.touch(section)
            orphaned.append(section)

    # level 2: in-flight runs whose scope contains an orphaned section.
    affected_runs = []
    affected_vendors = []
    for run in cascade.in_flight_runs():
        vendor = store.vendor_apps.get(run.get("vendor_app_id"))
        if vendor is None:
            continue
        scope = calc.resolve_scope(vendor, run.get("run_type"))
        in_scope = [s for s in scope.sections if s in orphaned]
        if not in_scope:
            continue
        for section in in_scope:
            cascade.raise_item(run, "UNMATCHED_TEACHER", "BLOCKING",
                               section.get("sis_section_id"),
                               section_id=section["id"])
        cascade.hold_run(run)
        cascade.recompute_run_counters(run)
        affected_runs.append(run)
        if vendor not in affected_vendors:
            affected_vendors.append(vendor)
    for vendor in affected_vendors:
        vendor["sync_health"] = "BLOCKED"
        store.touch(vendor)

    # level 3: the teacher's own identities go away for good, never SUSPENDED.
    for account in store.sorted_records(store.app_accounts):
        if (account.get("subject_type") == "TEACHER"
                and account.get("teacher_id") == teacher_id
                and account.get("identity_status") != "DEPROVISIONED"):
            cascade.deprovision_identity(account, effective)

    return envelope.ok(serial.teacher(teacher))


# ----------------------------------------------------------------- students
@bp.post("/rostering/students")
def create_student():
    auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    school_id = shape.req_id(body, "school_id")
    sis_student_id = shape.req_str(body, "sis_student_id", 1, 32)
    first_name = shape.req_str(body, "first_name", 1, 60)
    last_name = shape.req_str(body, "last_name", 1, 60)
    grade_level = shape.req_int(body, "grade_level", 0, 12)
    date_of_birth = shape.req_date(body, "date_of_birth")
    state_student_id = shape.opt_str(body, "state_student_id", None, 1, 32)
    school = fetch(store.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
    if school.get("status") != "ACTIVE":
        raise ApiError("ERR_SCHOOL_CLOSED", "The building is CLOSED.")
    for other in store.students.values():
        if other.get("sis_student_id") == sis_student_id:
            raise ApiError("ERR_DUPLICATE_SIS_ID",
                           "sis_student_id is already registered.")
    record = {
        "school_id": school_id,
        "sis_student_id": sis_student_id,
        "first_name": first_name,
        "last_name": last_name,
        "grade_level": grade_level,
        "date_of_birth": store.fmt_date(date_of_birth),
        "state_student_id": state_student_id,
        "enrollment_state": "ENROLLED",
        "withdrawal_effective_date": None,
        "duplicate_of_student_id": None,
        "active_enrollment_count": 0,
    }
    store.stamp_new(record)
    store.students[record["id"]] = record
    cascade.recompute_school_headcount(school)
    return envelope.created(serial.student(record))


@bp.post("/rostering/students/<student_id>/withdraw")
def withdraw_student(student_id):
    auth.require(auth.DATA_GOVERNANCE_OFFICER)
    student = fetch(store.students, student_id, "ERR_STUDENT_NOT_FOUND")
    body = shape.body()
    effective = shape.req_date(body, "withdrawal_effective_date")
    if student.get("enrollment_state") != "ENROLLED":
        raise ApiError("ERR_STUDENT_NOT_ENROLLED", "The student is not ENROLLED.")

    live = []
    for enrollment in store.sorted_records(store.enrollments):
        if enrollment.get("student_id") != student_id:
            continue
        if enrollment.get("roster_status") not in ("PENDING_ADD", "ACTIVE", "PENDING_DROP"):
            continue
        live.append(enrollment)
    for enrollment in live:
        section = store.sections.get(enrollment.get("section_id"))
        term = store.terms.get(section.get("term_id")) if section else None
        if term is None:
            continue
        if not (calc.as_date(term["start_date"]) <= effective
                <= calc.as_date(term["end_date"])):
            raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_TERM",
                           "The withdrawal date falls outside a term the "
                           "student is enrolled in.")

    # hop 2: wind the roster rows down (future-dated drops merely pend).
    today = store.clock_date()
    dropped_any = False
    sections_touched = []
    for enrollment in live:
        if enrollment.get("roster_status") not in ("PENDING_ADD", "ACTIVE"):
            continue
        enrollment["roster_status"] = "DROPPED" if effective <= today else "PENDING_DROP"
        enrollment["drop_effective_date"] = store.fmt_date(effective)
        store.touch(enrollment)
        if enrollment["roster_status"] == "DROPPED":
            dropped_any = True
        section = store.sections.get(enrollment.get("section_id"))
        if section is not None and section not in sections_touched:
            sections_touched.append(section)
    for section in sections_touched:
        cascade.recompute_section_count(section)

    # hop 1 proper: the student's own record is written exactly once.
    student["enrollment_state"] = "WITHDRAWN"
    student["withdrawal_effective_date"] = store.fmt_date(effective)
    student["active_enrollment_count"] = sum(
        1 for e in store.enrollments.values()
        if e.get("student_id") == student_id
        and e.get("roster_status") in ("PENDING_ADD", "ACTIVE", "PENDING_DROP"))
    store.touch(student)
    cascade.recompute_school_headcount(store.schools.get(student.get("school_id")))

    # hops 3 and 4: seats and identities, license counters recomputed per release.
    if dropped_any:
        cascade.release_student_seats(student, today, identity="DEPROVISIONED",
                                     deprovision_date=effective)

    return envelope.ok(serial.student(student))


# -------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require(*auth.ALL_ROLES)
    body = shape.body()
    moment = shape.req_instant(body, "now")
    store.set_clock(moment)
    return envelope.ok({"now": store.fmt_instant(moment)})
