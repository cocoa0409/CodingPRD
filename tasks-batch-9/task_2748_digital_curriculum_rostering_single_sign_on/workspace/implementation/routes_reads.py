"""Collection and single-record reads. Every read admits all five roles."""
from flask import Blueprint

import auth
import calc
import envelope
import serial
import shape
import store
from errors import ApiError

bp = Blueprint("reads", __name__)

ALL = auth.ALL_ROLES


def _page(records, serializer):
    limit, offset = shape.pagination()
    total = len(records)
    window = records[offset:offset + limit]
    return envelope.listing([serializer(r) for r in window], limit, offset, total)


def _filtered(collection, spec):
    """spec: {query_param: (field, kind)} with kind in ('str', 'int')."""
    records = store.sorted_records(collection)
    for param, (field, kind) in spec.items():
        if kind == "int":
            wanted = shape.qint(param)
        else:
            wanted = shape.qstr(param)
        if wanted is None:
            continue
        records = [r for r in records if r.get(field) == wanted]
    return records


def fetch(collection, record_id, error_id):
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


# ------------------------------------------------------------------ schools
@bp.get("/rostering/schools")
def list_schools():
    auth.require(*ALL)
    return _page(_filtered(store.schools, {
        "status": ("status", "str"),
        "grade_band": ("grade_band", "str"),
    }), serial.school)


@bp.get("/rostering/schools/<school_id>")
def read_school(school_id):
    auth.require(*ALL)
    return envelope.ok(serial.school(
        fetch(store.schools, school_id, "ERR_SCHOOL_NOT_FOUND")))


# -------------------------------------------------------------------- terms
@bp.get("/rostering/terms")
def list_terms():
    auth.require(*ALL)
    return _page(_filtered(store.terms, {
        "state": ("state", "str"),
        "school_year": ("school_year", "int"),
    }), serial.term)


@bp.get("/rostering/terms/<term_id>")
def read_term(term_id):
    auth.require(*ALL)
    return envelope.ok(serial.term(
        fetch(store.terms, term_id, "ERR_TERM_NOT_FOUND")))


# ----------------------------------------------------------------- teachers
@bp.get("/rostering/teachers")
def list_teachers():
    auth.require(*ALL)
    return _page(_filtered(store.teachers, {
        "school_id": ("school_id", "str"),
        "employment_status": ("employment_status", "str"),
    }), serial.teacher)


@bp.get("/rostering/teachers/<teacher_id>")
def read_teacher(teacher_id):
    auth.require(*ALL)
    return envelope.ok(serial.teacher(
        fetch(store.teachers, teacher_id, "ERR_TEACHER_NOT_FOUND")))


# ----------------------------------------------------------------- students
@bp.get("/rostering/students")
def list_students():
    auth.require(*ALL)
    return _page(_filtered(store.students, {
        "school_id": ("school_id", "str"),
        "duplicate_of_student_id": ("duplicate_of_student_id", "str"),
        "enrollment_state": ("enrollment_state", "str"),
        "grade_level": ("grade_level", "int"),
    }), serial.student)


@bp.get("/rostering/students/<student_id>")
def read_student(student_id):
    auth.require(*ALL)
    return envelope.ok(serial.student(
        fetch(store.students, student_id, "ERR_STUDENT_NOT_FOUND")))


# ----------------------------------------------------------------- sections
@bp.get("/rostering/sections")
def list_sections():
    auth.require(*ALL)
    return _page(_filtered(store.sections, {
        "school_id": ("school_id", "str"),
        "term_id": ("term_id", "str"),
        "primary_teacher_id": ("primary_teacher_id", "str"),
        "status": ("status", "str"),
        "roster_health": ("roster_health", "str"),
    }), serial.section)


@bp.get("/rostering/sections/<section_id>")
def read_section(section_id):
    auth.require(*ALL)
    section = fetch(store.sections, section_id, "ERR_SECTION_NOT_FOUND")
    if section.get("status") == "ARCHIVED":
        term = store.terms.get(section.get("term_id"))
        if not calc.archived_read_permitted(term):
            raise ApiError("ERR_ARCHIVE_WINDOW_CLOSED",
                           "The archived-access window for this term is shut.")
    return envelope.ok(serial.section(section))


# -------------------------------------------------------------- enrollments
@bp.get("/rostering/enrollments")
def list_enrollments():
    auth.require(*ALL)
    return _page(_filtered(store.enrollments, {
        "section_id": ("section_id", "str"),
        "student_id": ("student_id", "str"),
        "roster_status": ("roster_status", "str"),
        "add_drop_class": ("add_drop_class", "str"),
    }), serial.enrollment)


@bp.get("/rostering/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    auth.require(*ALL)
    return envelope.ok(serial.enrollment(
        fetch(store.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")))


# -------------------------------------------------------------- vendor apps
@bp.get("/rostering/vendor-apps")
def list_vendor_apps():
    auth.require(*ALL)
    return _page(_filtered(store.vendor_apps, {
        "term_id": ("term_id", "str"),
        "status": ("status", "str"),
        "rostering_standard": ("rostering_standard", "str"),
        "sync_health": ("sync_health", "str"),
    }), serial.vendor_app)


@bp.get("/rostering/vendor-apps/<vendor_app_id>")
def read_vendor_app(vendor_app_id):
    auth.require(*ALL)
    return envelope.ok(serial.vendor_app(
        fetch(store.vendor_apps, vendor_app_id, "ERR_VENDOR_APP_NOT_FOUND")))


# ------------------------------------------------------ building allocations
@bp.get("/rostering/building-allocations")
def list_building_allocations():
    auth.require(*ALL)
    return _page(_filtered(store.building_allocations, {
        "vendor_app_id": ("vendor_app_id", "str"),
        "school_id": ("school_id", "str"),
    }), serial.building_allocation)


@bp.get("/rostering/building-allocations/<building_allocation_id>")
def read_building_allocation(building_allocation_id):
    auth.require(*ALL)
    return envelope.ok(serial.building_allocation(fetch(
        store.building_allocations, building_allocation_id,
        "ERR_BUILDING_ALLOCATION_NOT_FOUND")))


# ------------------------------------------------------------- app accounts
@bp.get("/rostering/app-accounts")
def list_app_accounts():
    auth.require(*ALL)
    return _page(_filtered(store.app_accounts, {
        "building_allocation_id": ("building_allocation_id", "str"),
        "student_id": ("student_id", "str"),
        "teacher_id": ("teacher_id", "str"),
        "subject_type": ("subject_type", "str"),
        "seat_status": ("seat_status", "str"),
        "identity_status": ("identity_status", "str"),
        "password_state": ("password_state", "str"),
    }), serial.app_account)


@bp.get("/rostering/app-accounts/<app_account_id>")
def read_app_account(app_account_id):
    auth.require(*ALL)
    account = fetch(store.app_accounts, app_account_id, "ERR_APP_ACCOUNT_NOT_FOUND")
    if calc.evaluate_password_expiry(account):
        store.touch(account)
    return envelope.ok(serial.app_account(account))


# ---------------------------------------------------------------- sync runs
@bp.get("/rostering/sync-runs")
def list_sync_runs():
    auth.require(*ALL)
    return _page(_filtered(store.sync_runs, {
        "vendor_app_id": ("vendor_app_id", "str"),
        "state": ("state", "str"),
        "run_type": ("run_type", "str"),
    }), serial.sync_run)


@bp.get("/rostering/sync-runs/<sync_run_id>")
def read_sync_run(sync_run_id):
    auth.require(*ALL)
    return envelope.ok(serial.sync_run(
        fetch(store.sync_runs, sync_run_id, "ERR_SYNC_RUN_NOT_FOUND")))


# --------------------------------------------------------- error queue items
@bp.get("/rostering/error-queue-items")
def list_error_queue_items():
    auth.require(*ALL)
    return _page(_filtered(store.error_queue_items, {
        "sync_run_id": ("sync_run_id", "str"),
        "subject_section_id": ("subject_section_id", "str"),
        "subject_student_id": ("subject_student_id", "str"),
        "duplicate_candidate_student_id": ("duplicate_candidate_student_id", "str"),
        "category": ("category", "str"),
        "severity": ("severity", "str"),
        "status": ("status", "str"),
    }), serial.error_queue_item)


@bp.get("/rostering/error-queue-items/<error_queue_item_id>")
def read_error_queue_item(error_queue_item_id):
    auth.require(*ALL)
    return envelope.ok(serial.error_queue_item(fetch(
        store.error_queue_items, error_queue_item_id,
        "ERR_ERROR_QUEUE_ITEM_NOT_FOUND")))
