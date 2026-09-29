"""Employers, registration, headcount recounts and qualified-plan exemptions."""
from flask import Blueprint

import calc
import engine
import serializers
from auth import (get_certification, get_employer, own_employer, require)
from errors import fail
from response import created, paginate, query_filter, single
from store import db
from util import add_years, fmt_date, parse_date
from validate import parse_body, present

bp = Blueprint("employers", __name__)

PLAN_TYPES = ("401K", "403B", "SIMPLE_IRA", "SEP_IRA", "DEFINED_BENEFIT")
CERT_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "REVOKED")
PENALTY_STATUSES = ("ASSESSED", "ABATED", "AFFIRMED")
VIOLATION_TYPES = ("FAILURE_TO_REGISTER", "FAILURE_TO_REMIT", "FAILURE_TO_ENROLL")
ORIGINS = ("MANUAL", "SYSTEM_CASCADE", "SWEEP")

EMPLOYER_READ_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Employer"]
EMPLOYER_STAFF_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Employer"]


def _valid_ein(value):
    if len(value) != 10 or value[2] != "-":
        return False
    return value[0:2].isdigit() and value[3:].isdigit()


def _valid_state(value):
    return len(value) == 2 and value.isalpha() and value.isupper()


def _apply_tier(employer):
    tier, deadline = calc.coverage_tier(employer["employee_count"])
    employer["wave_tier"] = tier
    employer["registration_deadline"] = deadline
    return tier


@bp.route("/employers", methods=["POST"])
def create_employer():
    require(["ProgramAdministrator", "Employer"])
    parsed = parse_body({
        "ein": {"type": "str", "required": True},
        "legal_name": {"type": "str", "required": True},
        "worksite_state": {"type": "str", "required": True},
        "employee_count": {"type": "int", "required": True, "min": 0},
    })
    if not _valid_ein(parsed["ein"]):
        fail("ERR_INVALID_REQUEST", "ein must be written as NN-NNNNNNN")
    if not _valid_state(parsed["worksite_state"]):
        fail("ERR_INVALID_REQUEST", "worksite_state must be two uppercase letters")
    for existing in db.employers.values():
        if existing["ein"] == parsed["ein"]:
            fail("ERR_DUPLICATE_EIN", "an employer already exists for ein %s" % parsed["ein"])
    row = {
        "ein": parsed["ein"],
        "legal_name": parsed["legal_name"],
        "worksite_state": parsed["worksite_state"],
        "employee_count": parsed["employee_count"],
        "wave_tier": None,
        "registration_deadline": None,
        "registration_status": "PENDING_REGISTRATION",
        "compliance_status": "COMPLIANT",
        "non_fiduciary_acknowledged": False,
        "payroll_contact_email": None,
        "registered_at": None,
        "unremitted_deduction_cents": 0,
        "last_recount_effective_date": None,
    }
    tier = _apply_tier(row)
    if tier == "NOT_COVERED":
        row["registration_status"] = "EXEMPT_SMALL"
    db.insert("employers", row)
    return created(serializers.employer(row))


@bp.route("/employers/<employer_id>", methods=["GET"])
def read_employer(employer_id):
    principal = require(EMPLOYER_READ_ROLES)
    employer = get_employer(employer_id)
    own_employer(principal, employer_id)
    return single(serializers.employer(employer))


@bp.route("/employers/<employer_id>/registration", methods=["POST"])
def complete_registration(employer_id):
    principal = require(["Employer"])
    employer = get_employer(employer_id)
    own_employer(principal, employer_id)
    parsed = parse_body({
        "non_fiduciary_acknowledged": {"type": "bool", "required": True},
        "payroll_contact_email": {"type": "str", "required": True},
    })
    if parsed["non_fiduciary_acknowledged"] is not True:
        fail("ERR_INVALID_REQUEST",
             "non_fiduciary_acknowledged must be true for a registration")
    if employer["registration_status"] != "PENDING_REGISTRATION" or employer["wave_tier"] == "NOT_COVERED":
        fail("ERR_REGISTRATION_STATE_INVALID",
             "this employer is not awaiting registration")
    employer["registration_status"] = "REGISTERED"
    employer["non_fiduciary_acknowledged"] = True
    employer["payroll_contact_email"] = parsed["payroll_contact_email"]
    employer["registered_at"] = db.now_iso()
    db.touch(employer)
    return single(serializers.employer(employer))


@bp.route("/employers/<employer_id>/employee-count-recounts", methods=["POST"])
def recount_employees(employer_id):
    principal = require(["ProgramAdministrator", "Employer"])
    employer = get_employer(employer_id)
    own_employer(principal, employer_id)
    parsed = parse_body({
        "employee_count": {"type": "int", "required": True, "min": 0},
        "effective_date": {"type": "date", "required": True},
        "expected_employer_version": {"type": "int", "required": True},
    })
    if parsed["expected_employer_version"] != int(employer["version"]):
        fail("ERR_STALE_EMPLOYER_VERSION",
             "the employer has advanced to version %d" % int(employer["version"]))
    if calc.has_open_referral(employer_id):
        fail("ERR_ENFORCEMENT_HOLD",
             "this employer is under an open enforcement referral")
    employer["employee_count"] = parsed["employee_count"]
    tier = _apply_tier(employer)
    if tier == "NOT_COVERED":
        if employer["registration_status"] == "PENDING_REGISTRATION":
            employer["registration_status"] = "EXEMPT_SMALL"
    elif employer["registration_status"] == "EXEMPT_SMALL":
        employer["registration_status"] = "PENDING_REGISTRATION"
    employer["last_recount_effective_date"] = parsed["effective_date"]
    db.touch(employer)
    return single(serializers.employer(employer))


# ---------------------------------------------------- exemption certifications

@bp.route("/employers/<employer_id>/exemption-certifications", methods=["GET"])
def list_certifications(employer_id):
    principal = require(EMPLOYER_STAFF_ROLES)
    get_employer(employer_id)
    own_employer(principal, employer_id)
    status = query_filter("status", CERT_STATUSES)
    rows = [c for c in db.ordered("exemption_certifications") if c["employer_id"] == employer_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paginate(rows, serializers.certification)


@bp.route("/employers/<employer_id>/penalty-assessments", methods=["GET"])
def list_employer_penalties(employer_id):
    principal = require(EMPLOYER_STAFF_ROLES)
    get_employer(employer_id)
    own_employer(principal, employer_id)
    status = query_filter("status", PENALTY_STATUSES)
    violation_type = query_filter("violation_type", VIOLATION_TYPES)
    origin = query_filter("origin", ORIGINS)
    rows = [p for p in db.ordered("penalty_assessments") if p["employer_id"] == employer_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if violation_type is not None:
        rows = [p for p in rows if p["violation_type"] == violation_type]
    if origin is not None:
        rows = [p for p in rows if p["origin"] == origin]
    return paginate(rows, serializers.penalty)


@bp.route("/employers/<employer_id>/exemption-certifications", methods=["POST"])
def file_certification(employer_id):
    principal = require(["Employer", "ProgramAdministrator"])
    employer = get_employer(employer_id)
    own_employer(principal, employer_id)
    parsed = parse_body({
        "qualified_plan_type": {"type": "str", "required": True, "enum": PLAN_TYPES},
        "plan_sponsor_ein": {"type": "str", "required": True},
        "plan_effective_date": {"type": "date", "required": True},
        "attestation_accepted": {"type": "bool", "required": True},
    })
    if parsed["attestation_accepted"] is not True:
        fail("ERR_INVALID_REQUEST", "attestation_accepted must be true")
    start = parse_date(parsed["plan_effective_date"])
    end = add_years(start, 3)
    if calc.has_open_referral(employer_id):
        fail("ERR_ENFORCEMENT_HOLD", "this employer is under an open enforcement referral")
    for existing in engine.certifications_of(employer_id):
        if existing["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        other_start = parse_date(existing["coverage_period_start"])
        other_end = parse_date(existing["coverage_period_end"])
        if start < other_end and other_start < end:
            fail("ERR_EXEMPTION_PERIOD_OVERLAP",
                 "this coverage interval collides with a live certification")
    if end <= db.today():
        fail("ERR_EXEMPTION_WINDOW_CLOSED",
             "the three-year coverage window of this plan has already elapsed")
    row = db.insert("exemption_certifications", {
        "employer_id": employer_id,
        "qualified_plan_type": parsed["qualified_plan_type"],
        "plan_sponsor_ein": parsed["plan_sponsor_ein"],
        "plan_effective_date": parsed["plan_effective_date"],
        "attestation_accepted": True,
        "status": "SUBMITTED",
        "coverage_period_start": fmt_date(start),
        "coverage_period_end": fmt_date(end),
        "decision_note": None,
        "revocation_reason": None,
        "decided_at": None,
        "revoked_at": None,
    })
    return created(serializers.certification(row))


@bp.route("/exemption-certifications/<cert_id>", methods=["GET"])
def read_certification(cert_id):
    principal = require(EMPLOYER_STAFF_ROLES)
    cert = get_certification(cert_id)
    own_employer(principal, cert["employer_id"])
    return single(serializers.certification(cert))


@bp.route("/exemption-certifications/<cert_id>/decision", methods=["POST"])
def decide_certification(cert_id):
    require(["ProgramAdministrator"])
    cert = get_certification(cert_id)
    parsed = parse_body({
        "decision": {"type": "str", "required": True, "enum": ("APPROVE", "REJECT")},
        "decision_note": {"type": "str", "nullable": True},
    })
    if cert["status"] != "SUBMITTED":
        fail("ERR_EXEMPTION_STATE_INVALID", "this certification has already been decided")
    employer = db.employers.get(cert["employer_id"])
    if parsed["decision"] == "APPROVE":
        today = db.today()
        start = parse_date(cert["coverage_period_start"])
        end = parse_date(cert["coverage_period_end"])
        if today < start or today >= end:
            fail("ERR_EXEMPTION_STATE_INVALID",
                 "the clock is outside this certification's coverage interval")
        if engine.employer_has_active_enrollment(cert["employer_id"]):
            fail("ERR_EXEMPTION_STATE_INVALID",
                 "this employer still has active programme enrolments")
    cert["decided_at"] = db.now_iso()
    if present(parsed, "decision_note"):
        cert["decision_note"] = parsed["decision_note"]
    if parsed["decision"] == "REJECT":
        cert["status"] = "REJECTED"
        db.touch(cert)
        return single(serializers.certification(cert))
    cert["status"] = "APPROVED"
    db.touch(cert)
    if employer is not None:
        employer["registration_status"] = "EXEMPT_CERTIFIED"
        calc.refresh_employer(employer)
        db.touch(employer)
    return single(serializers.certification(cert))


@bp.route("/exemption-certifications/<cert_id>/revoke", methods=["POST"])
def revoke_certification(cert_id):
    require(["ComplianceOfficer"])
    cert = get_certification(cert_id)
    parsed = parse_body({"revocation_reason": {"type": "str", "required": True}})
    employer = db.employers.get(cert["employer_id"])
    if cert["status"] != "APPROVED" or employer is None or \
            employer["registration_status"] != "EXEMPT_CERTIFIED":
        fail("ERR_EXEMPTION_STATE_INVALID", "only an approved certification may be revoked")
    cert["status"] = "REVOKED"
    cert["revoked_at"] = db.now_iso()
    cert["revocation_reason"] = parsed["revocation_reason"]
    db.touch(cert)
    # The employer falls back onto the mandate it was excused from.
    employer["registration_status"] = "PENDING_REGISTRATION"
    affirmed = engine.affirmed_assessment_of(employer["id"])
    engine.mint_penalty(employer, "FAILURE_TO_REGISTER",
                        employer.get("registration_deadline"), 30, engine.SYSTEM,
                        "SYSTEM_CASCADE")
    if affirmed is not None:
        engine.mint_referral(affirmed, employer, "STATE_LABOR_COMMISSIONER",
                             "Exemption revoked while an affirmed assessment stood",
                             engine.SYSTEM)
    calc.refresh_employer(employer)
    db.touch(employer)
    return single(serializers.certification(cert))
