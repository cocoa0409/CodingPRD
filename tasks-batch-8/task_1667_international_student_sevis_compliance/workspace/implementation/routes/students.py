"""Student intake, financial documents, and address reports (PRD §3.1, §3.10)."""

import re
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from db import clock_date, new_id, parse_date, stamp_new, touch
from errors import (
    ERR_DOCUMENT_ALREADY_REVIEWED,
    ERR_DUPLICATE_SEVIS_ID,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_OWNED,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, req_date, req_enum,
    req_int, req_str, opt_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import (
    address_report_out, financial_document_out, student_out,
)

bp = Blueprint("students", __name__)

SEVIS_ID_RE = re.compile(r"^N[0-9]{10}$")
ALPHA2_RE = re.compile(r"^[A-Z]{2}$")

DOCUMENT_TYPES = ("BANK_STATEMENT", "SCHOLARSHIP_LETTER", "SPONSOR_AFFIDAVIT")
DEGREE_LEVELS = ("UNDERGRADUATE", "GRADUATE")
REVIEW_DECISIONS = ("VERIFIED", "REJECTED")


def _check_student_scope(user_id, role, student_id):
    """Student-role callers may only touch their own record (priority 2,
    before existence per PRD §2.9)."""
    if role == "Student" and user_id != student_id:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only act on their own resources")


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@bp.route("/sevis/students", methods=["POST"])
def create_student():
    require_roles(STAFF_ROLES)
    data = body()
    sevis_id = req_str(data, "sevis_id")
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    date_of_birth = req_date(data, "date_of_birth")
    country = req_str(data, "country_of_citizenship")
    degree_level = req_enum(data, "degree_level", DEGREE_LEVELS)
    if not SEVIS_ID_RE.match(sevis_id):
        raise_error(ERR_INVALID_REQUEST, "sevis_id must match ^N[0-9]{10}$")
    if not ALPHA2_RE.match(country):
        raise_error(ERR_INVALID_REQUEST, "country_of_citizenship must be an ISO 3166-1 alpha-2 code")
    for other in db.students.values():
        if other["sevis_id"] == sevis_id:
            raise_error(ERR_DUPLICATE_SEVIS_ID, "A student with this sevis_id already exists")
    student = {
        "id": new_id(),
        "sevis_id": sevis_id,
        "full_name": full_name,
        "email": email,
        "date_of_birth": date_of_birth,
        "country_of_citizenship": country,
        "degree_level": degree_level,
        "compliance_posture": "CLEAR",
    }
    stamp_new(student)
    db.students[student["id"]] = student
    return success_object(student_out(student), 201)


@bp.route("/sevis/students/<sid>", methods=["GET"])
def get_student(sid):
    user_id, role = require_roles(ALL_ROLES)
    _check_student_scope(user_id, role, sid)
    student = get_student_or_404(sid)
    return success_object(student_out(student), 200)


# ---------------------------------------------------------------------------
# Financial documents
# ---------------------------------------------------------------------------

@bp.route("/sevis/students/<sid>/financial-documents", methods=["POST"])
def create_financial_document(sid):
    user_id, role = require_roles(ALL_ROLES)
    _check_student_scope(user_id, role, sid)
    student = get_student_or_404(sid)
    data = body()
    document_type = req_enum(data, "document_type", DOCUMENT_TYPES)
    amount = req_int(data, "amount_usd_cents", min_value=0)
    issue_date = req_date(data, "issue_date")
    document = {
        "id": new_id(),
        "student_id": student["id"],
        "document_type": document_type,
        "amount_usd_cents": amount,
        "issue_date": issue_date,
        "status": "SUBMITTED",
        "review_note": None,
    }
    stamp_new(document)
    db.financial_documents[document["id"]] = document
    return success_object(financial_document_out(document), 201)


@bp.route("/sevis/students/<sid>/financial-documents", methods=["GET"])
def list_financial_documents(sid):
    user_id, role = require_roles(ALL_ROLES)
    _check_student_scope(user_id, role, sid)
    student = get_student_or_404(sid)
    items = [d for d in db.financial_documents.values() if d["student_id"] == student["id"]]
    return list_response(
        items,
        financial_document_out,
        {"status": request.args.get("status")},
    )


@bp.route("/sevis/financial-documents/<did>/review", methods=["POST"])
def review_financial_document(did):
    require_roles(STAFF_ROLES)
    document = get_or_404(db.financial_documents, did, "FinancialDocument")
    data = body()
    decision = req_enum(data, "decision", REVIEW_DECISIONS)
    note = opt_str(data, "note")
    if document["status"] != "SUBMITTED":
        raise_error(ERR_DOCUMENT_ALREADY_REVIEWED, "Document already VERIFIED or REJECTED")
    document["status"] = decision
    if note is not None:
        document["review_note"] = note
    touch(document)
    return success_object(financial_document_out(document), 200)


# ---------------------------------------------------------------------------
# Address reports (PRD §3.10): REPORTED within 10 days of move_date inclusive,
# else FLAGGED_LATE (which recomputes posture).
# ---------------------------------------------------------------------------

@bp.route("/sevis/students/<sid>/address-reports", methods=["POST"])
def create_address_report(sid):
    user_id, role = require_roles(ALL_ROLES)
    _check_student_scope(user_id, role, sid)
    student = get_student_or_404(sid)
    data = body()
    move_date = req_date(data, "move_date")
    address_line1 = req_str(data, "address_line1")
    city = req_str(data, "city")
    state_code = req_str(data, "state_code")
    postal_code = req_str(data, "postal_code")
    if not ALPHA2_RE.match(state_code):
        raise_error(ERR_INVALID_REQUEST, "state_code must be a 2-letter code")
    deadline = parse_date(move_date) + timedelta(days=services.ADDRESS_REPORT_WINDOW_DAYS)
    status = "REPORTED" if clock_date() <= deadline else "FLAGGED_LATE"
    report = {
        "id": new_id(),
        "student_id": student["id"],
        "move_date": move_date,
        "address_line1": address_line1,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
        "status": status,
    }
    stamp_new(report)
    db.address_reports[report["id"]] = report
    services.recompute_posture(student["id"])
    return success_object(address_report_out(report), 201)


@bp.route("/sevis/students/<sid>/address-reports", methods=["GET"])
def list_address_reports(sid):
    user_id, role = require_roles(ALL_ROLES)
    _check_student_scope(user_id, role, sid)
    student = get_student_or_404(sid)
    items = [a for a in db.address_reports.values() if a["student_id"] == student["id"]]
    return list_response(items, address_report_out)
