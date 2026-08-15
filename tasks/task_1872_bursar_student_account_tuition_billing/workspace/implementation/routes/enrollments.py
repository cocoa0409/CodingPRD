from flask import Blueprint, request

from db import store, base_fields, touch, clock_date
from dates import parse_date
from errors import (err, ERR_STUDENT_NOT_FOUND, ERR_TERM_NOT_FOUND,
                    ERR_ENROLLMENT_NOT_FOUND, ERR_TERM_NOT_OPEN,
                    ERR_ENROLLMENT_NOT_ACTIVE, ERR_REGISTRATION_HOLD_ACTIVE,
                    ERR_INVALID_REQUEST, ERR_CREDIT_HOURS_INVALID,
                    ERR_DROP_WINDOW_CLOSED, ERR_WITHDRAWAL_WINDOW_CLOSED)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_int, list_response
from serialize import ser_enrollment, ser_ledger_entry
from services.core import get_or_create_account, recompute_account
from services.domain import assess_tuition, create_refund, account_entries_for_enrollment

bp = Blueprint("enrollments", __name__)


@bp.post("/bursar/enrollments")
def create_enrollment():
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff")
    body = json_body()
    student_id = req_str(body, "student_id")
    term_id = req_str(body, "term_id")
    credit_hours = req_int(body, "credit_hours")
    if "effective_date" in body and body["effective_date"] is not None:
        effective = parse_date(body["effective_date"], "effective_date")
    else:
        effective = clock_date()

    # Ownership: a student may enroll only with their own student_id.
    if role == "Student" and student_id != uid:
        forbid()
    # Existence of body-supplied ids.
    student = store.students.get(student_id)
    if student is None:
        raise err(ERR_STUDENT_NOT_FOUND, "Student not found")
    term = store.terms.get(term_id)
    if term is None:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    # State: enrollment requires the term OPEN.
    if term["status"] != "OPEN":
        raise err(ERR_TERM_NOT_OPEN, "Enrollment requires the term to be OPEN")
    # Referential: an ACTIVE REGISTRATION hold on any account of the student
    # blocks enrollment.
    for a in store.accounts.values():
        if a["student_id"] != student_id:
            continue
        for h in store.holds.values():
            if (h["account_id"] == a["id"] and h["status"] == "ACTIVE"
                    and h["hold_type"] == "REGISTRATION"):
                raise err(ERR_REGISTRATION_HOLD_ACTIVE,
                          "Student has an active registration hold")
    # Temporal: effective date within [start_date, census_date].
    if not (parse_date(term["start_date"]) <= effective <= parse_date(term["census_date"])):
        raise err(ERR_INVALID_REQUEST,
                  "effective_date must be within [term.start_date, term.census_date]")
    # Fiscal: credit hours 1..24 inclusive.
    if not (1 <= credit_hours <= 24):
        raise err(ERR_CREDIT_HOURS_INVALID, "credit_hours must be between 1 and 24")

    account, _ = get_or_create_account(student_id, term_id)
    en = base_fields()
    en.update({
        "student_id": student_id, "term_id": term_id, "account_id": account["id"],
        "credit_hours": credit_hours, "effective_date": effective.isoformat(),
        "status": "ENROLLED", "exit_date": None, "assessed_total_cents": 0,
    })
    store.enrollments[en["id"]] = en
    assess_tuition(en, student, term)
    recompute_account(account, force_bump=True)
    return success(ser_enrollment(en), status=201)


@bp.get("/bursar/enrollments/<eid>")
def get_enrollment(eid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    en = store.enrollments.get(eid)
    if en is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    if role == "Student" and en["student_id"] != uid:
        forbid()
    return success(ser_enrollment(en))


@bp.get("/bursar/enrollments")
def list_enrollments():
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    rows = list(store.enrollments.values())
    if role == "Student":
        rows = [e for e in rows if e["student_id"] == uid]
    for key in ("student_id", "term_id", "account_id", "status"):
        v = request.args.get(key)
        if v is not None:
            rows = [e for e in rows if e[key] == v]
    rows.sort(key=lambda e: e["_seq"])
    return list_response(rows, ser_enrollment)


@bp.post("/bursar/enrollments/<eid>/drop")
def drop_enrollment(eid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff")
    en = store.enrollments.get(eid)
    if en is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    if role == "Student" and en["student_id"] != uid:
        forbid()
    body = json_body()
    if "effective_date" in body and body["effective_date"] is not None:
        effective = parse_date(body["effective_date"], "effective_date")
    else:
        effective = clock_date()
    if en["status"] != "ENROLLED":
        raise err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not active")
    term = store.terms[en["term_id"]]
    if term["status"] != "OPEN":
        raise err(ERR_TERM_NOT_OPEN, "Drop requires the term to be OPEN")
    if effective > parse_date(term["census_date"]):
        raise err(ERR_DROP_WINDOW_CLOSED, "Drop effective_date is after census_date")
    en["status"] = "DROPPED"
    en["exit_date"] = effective.isoformat()
    touch(en)
    create_refund(en, term, "DROP", effective)
    return success(ser_enrollment(en))


@bp.post("/bursar/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff")
    en = store.enrollments.get(eid)
    if en is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    if role == "Student" and en["student_id"] != uid:
        forbid()
    body = json_body()
    # effective_date is mandatory on withdraw.
    effective = parse_date(body.get("effective_date"), "effective_date")
    if en["status"] != "ENROLLED":
        raise err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not active")
    term = store.terms[en["term_id"]]
    if term["status"] not in ("OPEN", "CENSUS_LOCKED"):
        raise err(ERR_TERM_NOT_OPEN, "Withdraw requires the term to be OPEN or CENSUS_LOCKED")
    if not (parse_date(term["start_date"]) <= effective <= parse_date(term["withdrawal_deadline"])):
        raise err(ERR_WITHDRAWAL_WINDOW_CLOSED,
                  "Withdraw effective_date is outside [start_date, withdrawal_deadline]")
    en["status"] = "WITHDRAWN"
    en["exit_date"] = effective.isoformat()
    touch(en)
    create_refund(en, term, "WITHDRAWAL", effective)
    return success(ser_enrollment(en))


@bp.get("/bursar/enrollments/<eid>/ledger")
def enrollment_ledger(eid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    en = store.enrollments.get(eid)
    if en is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    if role == "Student" and en["student_id"] != uid:
        forbid()
    rows = account_entries_for_enrollment(eid)
    return list_response(rows, ser_ledger_entry)
