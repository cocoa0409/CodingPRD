"""SSO identities: provisioning, passwords, telemetry and the two-act wind-down."""
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

bp = Blueprint("identity", __name__)


def _account_or_scope(actor, app_account_id):
    """Scope (rung 3) is decided before the path identifier resolves (rung 5)."""
    account = store.app_accounts.get(app_account_id)
    vendor = cascade.vendor_of_account(account) if account is not None else None
    auth.vendor_scope(actor, vendor)
    if account is None:
        raise ApiError("ERR_APP_ACCOUNT_NOT_FOUND", "No such app account.")
    return account, vendor


# ------------------------------------------------------------ provisioning
@bp.post("/rostering/app-accounts")
def create_app_account():
    auth.require(auth.IDENTITY_ADMIN)
    body = shape.body()
    allocation_id = shape.req_id(body, "building_allocation_id")
    subject_type = shape.req_enum(body, "subject_type", shape.SUBJECT_TYPES)
    student_id = shape.opt_id(body, "student_id")
    teacher_id = shape.opt_id(body, "teacher_id")
    expected = shape.req_int(body, "expected_vendor_app_version", 1)
    if subject_type == "STUDENT":
        if student_id is None or teacher_id is not None:
            shape.bad("A STUDENT account carries student_id and no teacher_id.")
    else:
        if teacher_id is None or student_id is not None:
            shape.bad("A TEACHER account carries teacher_id and no student_id.")

    allocation = fetch(store.building_allocations, allocation_id,
                       "ERR_BUILDING_ALLOCATION_NOT_FOUND")
    if subject_type == "STUDENT":
        subject = fetch(store.students, student_id, "ERR_STUDENT_NOT_FOUND")
    else:
        subject = fetch(store.teachers, teacher_id, "ERR_TEACHER_NOT_FOUND")

    vendor = store.vendor_apps.get(allocation.get("vendor_app_id"))
    if vendor is None or vendor.get("version") != expected:
        raise ApiError("ERR_STALE_VENDOR_APP_VERSION",
                       "expected_vendor_app_version does not match the license.")
    if vendor.get("status") != "ACTIVE":
        raise ApiError("ERR_VENDOR_APP_NOT_ACTIVE", "The license is not ACTIVE.")
    if subject_type == "STUDENT":
        if subject.get("enrollment_state") != "ENROLLED":
            raise ApiError("ERR_STUDENT_NOT_ENROLLED", "The student is not ENROLLED.")
    elif subject.get("employment_status") != "ACTIVE":
        raise ApiError("ERR_TEACHER_SEPARATED", "The teacher is SEPARATED.")
    if subject.get("school_id") != allocation.get("school_id"):
        raise ApiError("ERR_SCHOOL_MISMATCH",
                       "The subject does not belong to the allocation's building.")

    username = calc.derive_username(vendor, subject_type, subject)

    for other in calc.vendor_accounts(vendor["id"]):
        if other.get("subject_type") != subject_type:
            continue
        key = "student_id" if subject_type == "STUDENT" else "teacher_id"
        if other.get(key) != subject["id"]:
            continue
        if other.get("seat_status") in ("RESERVED", "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_APP_ACCOUNT",
                           "The subject already holds a seat on this license.")

    subject_home = store.schools.get(subject.get("school_id"))
    band = calc.subject_band(subject_type, subject, subject_home)
    if band not in (vendor.get("grade_band_scope") or []):
        raise ApiError("ERR_GRADE_BAND_OUT_OF_SCOPE",
                       "The subject's own grade band is outside the license scope.")

    free = (allocation.get("allocated_seats") or 0) - (allocation.get("consumed_seats") or 0)
    borrowed = False
    if free < 1:
        if vendor.get("overage_policy") != "POOL_FALLBACK":
            raise ApiError("ERR_BUILDING_ALLOCATION_EXHAUSTED",
                           "The building's allocation is full under a hard cap.")
        if (vendor.get("unallocated_seats") or 0) < 1:
            raise ApiError("ERR_DISTRICT_SEATS_EXHAUSTED",
                           "The district seat pool is empty.")
        borrowed = True

    term = store.terms.get(vendor.get("term_id"))
    record = {
        "building_allocation_id": allocation_id,
        "student_id": student_id if subject_type == "STUDENT" else None,
        "teacher_id": teacher_id if subject_type == "TEACHER" else None,
        "subject_type": subject_type,
        "username": username,
        "seat_status": "RESERVED",
        "identity_status": "PENDING_PROVISION",
        "password_state": "TEMP_SET",
        "failed_login_count": 0,
        "last_password_set_at": None,
        "password_expires_at": None,
        "seat_charge_cents": calc.rate_for_date(vendor, term, store.clock_date()),
        "refunded_charge_cents": 0,
        "active_minutes_total": 0,
        "session_count": 0,
        "last_activity_date": None,
        "deprovision_scheduled_date": None,
        "_vendor_app_id": vendor["id"],
        "_borrowed_seat": borrowed,
    }
    store.stamp_new(record)
    record["password_expires_at"] = calc.temp_password_expiry(record, subject_home)
    store.app_accounts[record["id"]] = record
    cascade.recompute_vendor(vendor, bump_version=True)
    return envelope.created(serial.app_account(record))


# ---------------------------------------------------------------- passwords
@bp.post("/rostering/app-accounts/<app_account_id>/password-set")
def set_password(app_account_id):
    auth.require(auth.IDENTITY_ADMIN)
    account = fetch(store.app_accounts, app_account_id, "ERR_APP_ACCOUNT_NOT_FOUND")
    body = shape.body()
    new_password = shape.req_str(body, "new_password", 1, 128)
    if account.get("identity_status") == "DEPROVISIONED":
        raise ApiError("ERR_ACCOUNT_DEPROVISIONED", "The identity is frozen.")
    if account.get("password_state") == "LOCKED":
        raise ApiError("ERR_ACCOUNT_LOCKED", "The password is locked.")
    school = calc.subject_school(account)
    calc.check_password_policy(school, new_password)

    now = store.clock_now()
    if account.get("identity_status") in ("PENDING_PROVISION", "SUSPENDED"):
        account["identity_status"] = "PROVISIONED"
    account["password_state"] = "USER_SET"
    account["failed_login_count"] = 0
    account["last_password_set_at"] = store.fmt_instant(now)
    account["password_expires_at"] = calc.user_password_expiry(now, school)
    store.touch(account)
    return envelope.ok(serial.app_account(account))


# ---------------------------------------------------------------- telemetry
@bp.post("/rostering/app-accounts/<app_account_id>/record-usage")
def record_usage(app_account_id):
    actor = auth.require(auth.IDENTITY_ADMIN, auth.VENDOR_INTEGRATION_MANAGER)
    account, vendor = _account_or_scope(actor, app_account_id)
    body = shape.body()
    activity_date = shape.req_date(body, "activity_date")
    active_minutes = shape.req_int(body, "active_minutes", 0, 100000)
    session_count = shape.opt_int(body, "session_count", 0, 0, 100000)
    failed_logins = shape.opt_int(body, "failed_logins", 0, 0, 100000)
    if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
        raise ApiError("ERR_SEAT_ALREADY_RELEASED", "The seat is already released.")
    if account.get("identity_status") == "DEPROVISIONED":
        raise ApiError("ERR_ACCOUNT_DEPROVISIONED", "The identity is frozen.")

    calc.evaluate_password_expiry(account)
    account["active_minutes_total"] = (account.get("active_minutes_total") or 0) + active_minutes
    account["session_count"] = (account.get("session_count") or 0) + session_count
    account["last_activity_date"] = store.fmt_date(activity_date)
    if active_minutes > 0 and account.get("seat_status") == "RESERVED":
        account["seat_status"] = "ACTIVE"
    if failed_logins:
        account["failed_login_count"] = (account.get("failed_login_count") or 0) + failed_logins
    school = calc.subject_school(account)
    threshold = (school.get("password_lockout_threshold") if school else None) or 5
    if (account.get("failed_login_count") or 0) >= threshold:
        account["password_state"] = "LOCKED"
    store.touch(account)
    cascade.recompute_vendor(vendor, bump_version=True)
    return envelope.ok(serial.app_account(account))


# -------------------------------------------------------------- wind-down
@bp.post("/rostering/app-accounts/<app_account_id>/release")
def release_seat(app_account_id):
    auth.require(auth.IDENTITY_ADMIN)
    account = fetch(store.app_accounts, app_account_id, "ERR_APP_ACCOUNT_NOT_FOUND")
    if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
        raise ApiError("ERR_SEAT_ALREADY_RELEASED", "The seat is already released.")
    cascade.release_seat(account, store.clock_date())
    return envelope.ok(serial.app_account(account))


@bp.post("/rostering/app-accounts/<app_account_id>/deprovision")
def deprovision(app_account_id):
    auth.require(auth.IDENTITY_ADMIN)
    account = fetch(store.app_accounts, app_account_id, "ERR_APP_ACCOUNT_NOT_FOUND")
    body = shape.body()
    effective = shape.req_date(body, "effective_date")
    if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
        raise ApiError("ERR_SEAT_ALREADY_RELEASED", "The seat is already released.")
    if account.get("identity_status") == "DEPROVISIONED":
        raise ApiError("ERR_ACCOUNT_DEPROVISIONED", "The identity is already gone.")
    today = store.clock_date()
    if effective > today:
        raise ApiError("ERR_DEPROVISION_NOT_DUE",
                       "A deprovision is never post-dated.")
    scheduled = account.get("deprovision_scheduled_date")
    if scheduled and today < calc.as_date(scheduled):
        raise ApiError("ERR_DEPROVISION_NOT_DUE",
                       "The scheduled deprovision date has not arrived.")

    account["identity_status"] = "DEPROVISIONED"
    account["deprovision_scheduled_date"] = store.fmt_date(effective)
    account["password_state"] = "EXPIRED"
    store.touch(account)
    cascade.recompute_vendor(cascade.vendor_of_account(account), bump_version=True)
    return envelope.ok(serial.app_account(account))
