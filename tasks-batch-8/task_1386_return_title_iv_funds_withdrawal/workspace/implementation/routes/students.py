"""Students and enrollments (including withdraw/rescind/complete/payments)."""

import uuid

import clock
import db
import errors
import serializers
from flask import Blueprint, request
from middleware import (ALL_ROLES, get_auth, require_roles, parse_json_body,
                        parse_pagination)
from response import success_object, success_list
from services import calc
from services.term_days import parse_date

bp = Blueprint("students", __name__)


# ---------------------------------------------------------------- students

@bp.post("/r2t4/students")
def create_student():
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk"])
    body = parse_json_body()
    external_ref = body.get("external_ref")
    full_name = body.get("full_name")
    email = body.get("email")
    if external_ref is None or full_name is None or email is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "external_ref, full_name and email are required")
    for field, value in (("external_ref", external_ref),
                         ("full_name", full_name), ("email", email)):
        if not isinstance(value, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"{field} must be a string")
    student = {
        "id": str(uuid.uuid4()),
        "external_ref": external_ref,
        "full_name": full_name,
        "email": email,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.students[student["id"]] = student
    return success_object(serializers.student(student), status_code=201)


@bp.get("/r2t4/students/<student_id>")
def get_student(student_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    student = db.students.get(student_id)
    if student is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "student not found")
    return success_object(serializers.student(student))


# ---------------------------------------------------------------- enrollments

@bp.post("/r2t4/students/<student_id>/enrollments")
def create_enrollment(student_id):
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk"])
    student = db.students.get(student_id)
    if student is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "student not found")
    body = parse_json_body()
    term_id = body.get("term_id")
    charges = body.get("institutional_charges_cents")
    if term_id is None or charges is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "term_id and institutional_charges_cents are required")
    if not isinstance(term_id, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "term_id must be a string")
    if not isinstance(charges, int) or isinstance(charges, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "institutional_charges_cents must be an integer")
    if charges < 0:
        errors.raise_error(errors.ERR_INVALID_FIELD,
                           "institutional_charges_cents must be >= 0")
    if term_id not in db.terms:
        errors.raise_error(errors.ERR_NOT_FOUND, "term not found")

    enrollment = {
        "id": str(uuid.uuid4()),
        "student_id": student_id,
        "term_id": term_id,
        "institutional_charges_cents": charges,
        "status": "ENROLLED",
        "balance_cents": 0,
        "balance_notification_sent": False,
        "balance_notified_at": None,
        "current_withdrawal_case_id": None,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.enrollments[enrollment["id"]] = enrollment
    if charges > 0:
        calc.post_entry(enrollment["id"], "CHARGE", charges, source_ref="")
    calc.recompute_balance(enrollment["id"])
    return success_object(serializers.enrollment(enrollment), status_code=201)


@bp.get("/r2t4/enrollments")
def list_enrollments():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.enrollments.values())
    student_id = request.args.get("student_id")
    term_id = request.args.get("term_id")
    status = request.args.get("status")
    if student_id is not None:
        items = [e for e in items if e["student_id"] == student_id]
    if term_id is not None:
        items = [e for e in items if e["term_id"] == term_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.enrollment(e) for e in page],
                        total, limit, offset)


@bp.get("/r2t4/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "enrollment not found")
    return success_object(serializers.enrollment(enrollment))


def _get_enrollment_or_404(enrollment_id):
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "enrollment not found")
    return enrollment


def _validate_withdrawal_payload(enrollment, term, body, auth):
    """Shared validation for withdraw + recalculate corrections. Returns a
    dict with withdrawal_type / notification_date / last_attendance_date."""
    withdrawal_type = body.get("withdrawal_type")
    if withdrawal_type is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "withdrawal_type is required")
    if withdrawal_type not in ("OFFICIAL", "UNOFFICIAL"):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "withdrawal_type must be OFFICIAL or UNOFFICIAL")

    notification_date = body.get("notification_date")
    last_attendance_date = body.get("last_attendance_date")

    if withdrawal_type == "OFFICIAL" and notification_date is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "notification_date is required for OFFICIAL withdrawal")
    if (withdrawal_type == "UNOFFICIAL"
            and term["attendance_taking_required"]
            and last_attendance_date is None):
        errors.raise_error(errors.ERR_ATTENDANCE_DATE_REQUIRED,
                           "last_attendance_date is required for UNOFFICIAL withdrawal "
                           "on an attendance-taking term")

    t_start = parse_date(term["start_date"])
    t_end = parse_date(term["end_date"])
    for label, value in (("notification_date", notification_date),
                         ("last_attendance_date", last_attendance_date)):
        if value is not None:
            parsed = parse_date(value)
            if parsed is None:
                errors.raise_error(errors.ERR_INVALID_REQUEST,
                                   f"{label} must be an ISO date (YYYY-MM-DD)")
            if parsed < t_start or parsed > t_end:
                errors.raise_error(errors.ERR_DATE_OUT_OF_PERIOD,
                                   f"{label} lies outside the payment period")

    return {
        "withdrawal_type": withdrawal_type,
        "notification_date": notification_date,
        "last_attendance_date": last_attendance_date,
    }


@bp.post("/r2t4/enrollments/<enrollment_id>/withdraw")
def withdraw(enrollment_id):
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk", "Student"])
    body = parse_json_body()
    enrollment = _get_enrollment_or_404(enrollment_id)
    term = db.terms[enrollment["term_id"]]

    # Priority 5: student ownership.
    if auth.is_student and enrollment["student_id"] != auth.user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_MISMATCH,
                           "students may only act on their own enrollment")

    # Priority 2 nuance: Student may only initiate OFFICIAL withdrawals.
    withdrawal_type = body.get("withdrawal_type")
    if auth.is_student and withdrawal_type == "UNOFFICIAL":
        errors.raise_error(errors.ERR_FORBIDDEN_FOR_ROLE,
                           "students may only initiate OFFICIAL withdrawals")

    # Priority 6: enrollment state.
    if enrollment["status"] == "WITHDRAWN":
        errors.raise_error(errors.ERR_ENROLLMENT_ALREADY_WITHDRAWN,
                           "enrollment is already withdrawn")
    if enrollment["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "only an ENROLLED enrollment can be withdrawn")

    inputs = _validate_withdrawal_payload(enrollment, term, body, auth)

    case = {
        "id": str(uuid.uuid4()),
        "enrollment_id": enrollment["id"],
        "withdrawal_type": inputs["withdrawal_type"],
        "notification_date": inputs["notification_date"],
        "last_attendance_date": inputs["last_attendance_date"],
        "withdrawal_date": None,
        "determination_date": None,
        "total_days": None,
        "completed_days": None,
        "percentage_completed": None,
        "earned_pct": None,
        "aid_disbursable_cents": None,
        "aid_disbursed_cents": None,
        "aid_earned_cents": None,
        "aid_unearned_cents": None,
        "return_amount_cents": None,
        "school_return_cents": None,
        "student_grant_return_cents": None,
        "student_loan_deferred_cents": None,
        "pwd_grant_cents": None,
        "pwd_loan_cents": None,
        "status": "OPEN",
        "calculated_by_user_id": None,
        "calculated_at": None,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.withdrawal_cases[case["id"]] = case
    calc.determine_dates_and_progress(case, term, clock.current_date())

    enrollment["status"] = "WITHDRAWN"
    enrollment["current_withdrawal_case_id"] = case["id"]
    enrollment["version"] += 1
    enrollment["updated_at"] = clock.now_iso()

    return success_object(serializers.withdrawal_case(case), status_code=201)


@bp.post("/r2t4/enrollments/<enrollment_id>/rescind-withdrawal")
def rescind_withdrawal(enrollment_id):
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk"])
    parse_json_body()
    enrollment = _get_enrollment_or_404(enrollment_id)

    if enrollment["status"] != "WITHDRAWN":
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_WITHDRAWN,
                           "enrollment is not currently withdrawn")

    case_id = enrollment.get("current_withdrawal_case_id")
    case = db.withdrawal_cases.get(case_id) if case_id else None
    if case is None:
        # The case that drove the current withdrawal may have auto-CLOSED,
        # which clears current_withdrawal_case_id (see section 3.7 closure).
        # Recover it by reverse lookup: the most recent non-CANCELLED case
        # of this enrollment.
        candidates = [c for c in db.withdrawal_cases.values()
                      if c["enrollment_id"] == enrollment["id"]
                      and c["status"] != "CANCELLED"]
        if candidates:
            case = max(candidates, key=lambda c: c["_seq"])
    if case is not None and case["status"] == "CLOSED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "a closed withdrawal case cannot be rescinded")

    if case is not None:
        for obligation in db.obligations.values():
            if (obligation["withdrawal_case_id"] == case["id"]
                    and obligation["status"] == "RETURNED"):
                errors.raise_error(errors.ERR_RETURN_ALREADY_COMPLETED,
                                   "an obligation of the case is already returned")
        for offer in db.offers.values():
            if (offer["withdrawal_case_id"] == case["id"]
                    and offer["status"] == "ACCEPTED"):
                errors.raise_error(errors.ERR_OFFER_ALREADY_ACCEPTED,
                                   "an offer of the case is already accepted")

    if case is not None:
        if case["status"] == "CALCULATED":
            calc.compensate_case_artifacts(case)
        case["status"] = "CANCELLED"
        case["version"] += 1
        case["updated_at"] = clock.now_iso()

    calc.recompute_balance(enrollment["id"], evaluate_notification=False)
    enrollment["status"] = "ENROLLED"
    enrollment["balance_notification_sent"] = False
    enrollment["balance_notified_at"] = None
    enrollment["current_withdrawal_case_id"] = None
    enrollment["version"] += 1
    enrollment["updated_at"] = clock.now_iso()

    return success_object(serializers.enrollment(enrollment))


@bp.post("/r2t4/enrollments/<enrollment_id>/complete")
def complete_enrollment(enrollment_id):
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk"])
    parse_json_body()
    enrollment = _get_enrollment_or_404(enrollment_id)

    if enrollment["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "only an ENROLLED enrollment can be completed")
    term = db.terms[enrollment["term_id"]]
    if clock.current_date() <= parse_date(term["end_date"]):
        errors.raise_error(errors.ERR_TERM_NOT_ENDED,
                           "the term has not yet ended")

    for award in db.awards.values():
        if award["enrollment_id"] != enrollment["id"]:
            continue
        changed = False
        for d in db.disbursements.values():
            if d["award_id"] == award["id"] and d["status"] == "SCHEDULED":
                d["status"] = "CANCELLED"
                d["updated_at"] = clock.now_iso()
                d["version"] += 1
                award["scheduled_amount_cents"] -= d["amount_cents"]
                changed = True
        if changed:
            award["updated_at"] = clock.now_iso()

    enrollment["status"] = "COMPLETED"
    enrollment["version"] += 1
    enrollment["updated_at"] = clock.now_iso()
    return success_object(serializers.enrollment(enrollment))


@bp.post("/r2t4/enrollments/<enrollment_id>/payments")
def create_payment(enrollment_id):
    auth = get_auth()
    require_roles(auth, ["BursarClerk", "Student"])
    body = parse_json_body()
    enrollment = _get_enrollment_or_404(enrollment_id)

    amount = body.get("amount_cents")
    if amount is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "amount_cents is required")
    if not isinstance(amount, int) or isinstance(amount, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "amount_cents must be an integer")
    if amount <= 0:
        errors.raise_error(errors.ERR_INVALID_FIELD,
                           "amount_cents must be positive")

    if auth.is_student and enrollment["student_id"] != auth.user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_MISMATCH,
                           "students may only pay toward their own enrollment")

    entry = calc.post_entry(enrollment["id"], "PAYMENT", -amount, source_ref="")
    calc.recompute_balance(enrollment["id"])
    enrollment["updated_at"] = clock.now_iso()
    return success_object(serializers.account_entry(entry), status_code=201)


@bp.get("/r2t4/enrollments/<enrollment_id>/awards")
def list_enrollment_awards(enrollment_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    _get_enrollment_or_404(enrollment_id)
    limit, offset = parse_pagination(request.args)
    items = [a for a in db.awards.values()
             if a["enrollment_id"] == enrollment_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.award(a) for a in page], total, limit, offset)


@bp.get("/r2t4/enrollments/<enrollment_id>/account-entries")
def list_enrollment_entries(enrollment_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    _get_enrollment_or_404(enrollment_id)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.account_entries.values()
             if e["enrollment_id"] == enrollment_id]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.account_entry(e) for e in page],
                        total, limit, offset)
