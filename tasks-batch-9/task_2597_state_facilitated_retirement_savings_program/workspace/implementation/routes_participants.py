"""Participants and the enrolment lifecycle."""
from flask import Blueprint

import calc
import serializers
from auth import (ALL_ROLES, get_employer, get_enrollment, get_participant,
                  own_employer, own_participant, require)
from errors import fail
from response import (created, paginate, query_bool, query_filter, single)
from store import db
from util import add_days, fmt_date, parse_date
from validate import parse_body, present

bp = Blueprint("participants", __name__)

PARTICIPANT_READ_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Participant"]
ENROLLMENT_STATUSES = ("NOTIFIED", "ACTIVE", "OPTED_OUT", "TERMINATED")
RATE_SOURCES = ("DEFAULT", "PARTICIPANT_ELECTED", "ESCALATED")
OPT_OUT_REASONS = ("NOT_INTERESTED", "HAS_OTHER_PLAN", "AFFORDABILITY", "OTHER")
LINE_STATUSES = ("PENDING", "POSTED", "REVERSED", "RETURNED")


def _enrollment_scope(principal, enrollment):
    own_employer(principal, enrollment["employer_id"])
    own_participant(principal, enrollment["participant_id"])


@bp.route("/participants", methods=["POST"])
def create_participant():
    require(["ProgramAdministrator"])
    parsed = parse_body({
        "full_name": {"type": "str", "required": True},
        "date_of_birth": {"type": "date", "required": True},
        "email": {"type": "str", "required": True},
        "ssn_last4": {"type": "str", "required": True},
        "state_resident": {"type": "bool", "required": True},
        "mailing_address": {"type": "str", "nullable": True},
        "phone": {"type": "str", "nullable": True},
    })
    if len(parsed["ssn_last4"]) != 4 or not parsed["ssn_last4"].isdigit():
        fail("ERR_INVALID_REQUEST", "ssn_last4 must be exactly four digits")
    row = db.insert("participants", {
        "full_name": parsed["full_name"],
        "date_of_birth": parsed["date_of_birth"],
        "email": parsed["email"],
        "ssn_last4": parsed["ssn_last4"],
        "state_resident": parsed["state_resident"],
        "mailing_address": parsed["mailing_address"],
        "phone": parsed["phone"],
    })
    return created(serializers.participant(row))


@bp.route("/participants/<participant_id>", methods=["GET"])
def read_participant(participant_id):
    principal = require(PARTICIPANT_READ_ROLES)
    participant = get_participant(participant_id)
    own_participant(principal, participant_id)
    return single(serializers.participant(participant))


@bp.route("/participants", methods=["GET"])
def list_participants():
    require(["ProgramAdministrator", "ComplianceOfficer"])
    state_resident = query_bool("state_resident")
    catch_up = query_bool("catch_up_eligible")
    rows = db.ordered("participants")
    if state_resident is not None:
        rows = [p for p in rows if bool(p["state_resident"]) is state_resident]
    if catch_up is not None:
        rows = [p for p in rows if calc.catch_up_eligible(p) is catch_up]
    return paginate(rows, serializers.participant)


@bp.route("/participants/<participant_id>", methods=["PATCH"])
def update_participant(participant_id):
    principal = require(["Participant", "ProgramAdministrator"])
    participant = get_participant(participant_id)
    own_participant(principal, participant_id)
    parsed = parse_body({
        "email": {"type": "str"},
        "mailing_address": {"type": "str", "nullable": True},
        "phone": {"type": "str", "nullable": True},
    })
    for name in ("email", "mailing_address", "phone"):
        if present(parsed, name):
            participant[name] = parsed[name]
    db.touch(participant)
    return single(serializers.participant(participant))


# ------------------------------------------------------------------ enrolments

@bp.route("/employers/<employer_id>/enrollments", methods=["POST"])
def create_enrollment(employer_id):
    principal = require(["Employer", "ProgramAdministrator"])
    employer = get_employer(employer_id)
    own_employer(principal, employer_id)
    parsed = parse_body({
        "participant_id": {"type": "str", "required": True},
        "hire_date": {"type": "date", "required": True},
        "annual_compensation_cents": {"type": "int", "required": True, "min": 0},
    })
    participant = get_participant(parsed["participant_id"])
    if employer["registration_status"] != "REGISTERED":
        fail("ERR_EMPLOYER_NOT_REGISTERED",
             "only a registered employer may enrol employees")
    year = calc.program_year()
    for existing in db.enrollments.values():
        if existing["employer_id"] != employer_id:
            continue
        if existing["participant_id"] != participant["id"]:
            continue
        if existing["enrollment_status"] in ("NOTIFIED", "ACTIVE", "OPTED_OUT"):
            fail("ERR_DUPLICATE_ENROLLMENT",
                 "a live enrolment already exists for this employer and saver")
    deadline = add_days(db.today(), int(year["opt_out_window_days"]))
    row = db.insert("enrollments", {
        "employer_id": employer_id,
        "participant_id": participant["id"],
        "hire_date": parsed["hire_date"],
        "annual_compensation_cents": parsed["annual_compensation_cents"],
        "contribution_rate_bp": int(year["default_contribution_rate_bp"]),
        "rate_source": "DEFAULT",
        "enrollment_status": "NOTIFIED",
        "opt_out_deadline": fmt_date(deadline),
        "escalation_opt_out": False,
        "employment_end_date": None,
        "opted_out_at": None,
        "opt_out_reason_code": None,
        "permissible_withdrawal_cents": 0,
        "reenrollment_count": 0,
    })
    return created(serializers.enrollment(row))


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def read_enrollment(enrollment_id):
    principal = require(ALL_ROLES)
    enrollment = get_enrollment(enrollment_id)
    _enrollment_scope(principal, enrollment)
    return single(serializers.enrollment(enrollment))


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    principal = require(ALL_ROLES)
    employer_id = query_filter("employer_id")
    participant_id = query_filter("participant_id")
    status = query_filter("enrollment_status", ENROLLMENT_STATUSES)
    rate_source = query_filter("rate_source", RATE_SOURCES)
    rows = db.ordered("enrollments")
    if principal.is_employer:
        rows = [e for e in rows if e["employer_id"] == principal.user_id]
    if principal.is_participant:
        rows = [e for e in rows if e["participant_id"] == principal.user_id]
    if employer_id is not None:
        rows = [e for e in rows if e["employer_id"] == employer_id]
    if participant_id is not None:
        rows = [e for e in rows if e["participant_id"] == participant_id]
    if status is not None:
        rows = [e for e in rows if e["enrollment_status"] == status]
    if rate_source is not None:
        rows = [e for e in rows if e["rate_source"] == rate_source]
    return paginate(rows, serializers.enrollment)


@bp.route("/enrollments/<enrollment_id>/opt-out", methods=["POST"])
def opt_out(enrollment_id):
    principal = require(["Participant", "ProgramAdministrator", "Employer"])
    enrollment = get_enrollment(enrollment_id)
    _enrollment_scope(principal, enrollment)
    parsed = parse_body({
        "opt_out_reason_code": {"type": "str", "required": True, "enum": OPT_OUT_REASONS},
        "request_permissible_withdrawal": {"type": "bool", "default": False},
    })
    if enrollment["enrollment_status"] not in ("NOTIFIED", "ACTIVE"):
        fail("ERR_ENROLLMENT_STATE_INVALID", "this enrolment cannot be opted out of")
    if principal.is_employer:
        fail("ERR_FIDUCIARY_BOUNDARY_VIOLATION",
             "an employer may not opt a saver out of the programme")
    today = db.today()
    if enrollment["enrollment_status"] == "NOTIFIED" and \
            today >= parse_date(enrollment["opt_out_deadline"]):
        fail("ERR_OPT_OUT_WINDOW_CLOSED",
             "the pre-activation opt-out window has closed")
    withdrawal = bool(parsed["request_permissible_withdrawal"])
    first = calc.first_contribution_date(enrollment_id)
    if withdrawal:
        window_days = int(calc.dial("opt_out_window_days"))
        if not first or today > add_days(parse_date(first), window_days):
            fail("ERR_PERMISSIBLE_WITHDRAWAL_WINDOW_CLOSED",
                 "the permissible-withdrawal window is not open")
    enrollment["enrollment_status"] = "OPTED_OUT"
    enrollment["opted_out_at"] = db.now_iso()
    enrollment["opt_out_reason_code"] = parsed["opt_out_reason_code"]
    if withdrawal:
        amount = calc.lifetime_deducted_cents(enrollment_id)
        enrollment["permissible_withdrawal_cents"] = amount
        account = calc.posting_target_account(enrollment["participant_id"])
        if account is not None and amount:
            account["balance_cents"] = int(account["balance_cents"]) - amount
            account["contribution_basis_cents"] = int(account["contribution_basis_cents"]) - amount
            calc.refresh_account(account, bump=True)
    db.touch(enrollment)
    return single(serializers.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/reenroll", methods=["POST"])
def reenroll(enrollment_id):
    principal = require(["Participant", "ProgramAdministrator"])
    enrollment = get_enrollment(enrollment_id)
    _enrollment_scope(principal, enrollment)
    parse_body({"reenroll_note": {"type": "str", "nullable": True}})
    if enrollment["enrollment_status"] != "OPTED_OUT" or enrollment["employment_end_date"]:
        fail("ERR_ENROLLMENT_STATE_INVALID", "only an opted-out enrolment may be re-enrolled")
    employer = db.employers.get(enrollment["employer_id"])
    if employer is None or employer["registration_status"] != "REGISTERED":
        fail("ERR_EMPLOYER_NOT_REGISTERED", "this employer is no longer registered")
    year = calc.program_year()
    enrollment["enrollment_status"] = "ACTIVE"
    enrollment["contribution_rate_bp"] = int(year["default_contribution_rate_bp"])
    enrollment["rate_source"] = "DEFAULT"
    enrollment["escalation_opt_out"] = False
    enrollment["reenrollment_count"] = int(enrollment["reenrollment_count"]) + 1
    enrollment["opted_out_at"] = None
    enrollment["opt_out_reason_code"] = None
    db.touch(enrollment)
    return single(serializers.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/rate-election", methods=["POST"])
def rate_election(enrollment_id):
    principal = require(["Participant", "ProgramAdministrator", "Employer"])
    enrollment = get_enrollment(enrollment_id)
    _enrollment_scope(principal, enrollment)
    parsed = parse_body({
        "contribution_rate_bp": {"type": "int", "required": True},
        "escalation_opt_out": {"type": "bool"},
    })
    if enrollment["enrollment_status"] not in ("NOTIFIED", "ACTIVE"):
        fail("ERR_ENROLLMENT_STATE_INVALID", "this enrolment cannot take a rate election")
    if principal.is_employer:
        fail("ERR_FIDUCIARY_BOUNDARY_VIOLATION",
             "an employer may not choose a saver's deferral rate")
    rate = parsed["contribution_rate_bp"]
    if rate < calc.MIN_PARTICIPANT_RATE_BP or rate > calc.MAX_PARTICIPANT_RATE_BP:
        fail("ERR_RATE_OUT_OF_BOUNDS",
             "an elected deferral rate must be between 100 and 1500 basis points")
    enrollment["contribution_rate_bp"] = rate
    enrollment["rate_source"] = "PARTICIPANT_ELECTED"
    if present(parsed, "escalation_opt_out"):
        enrollment["escalation_opt_out"] = bool(parsed["escalation_opt_out"])
    db.touch(enrollment)
    return single(serializers.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/employment", methods=["PATCH"])
def update_employment(enrollment_id):
    principal = require(["Employer"])
    enrollment = get_enrollment(enrollment_id)
    _enrollment_scope(principal, enrollment)
    parsed = parse_body({"employment_end_date": {"type": "date", "required": True}})
    if enrollment["enrollment_status"] == "TERMINATED":
        fail("ERR_ENROLLMENT_STATE_INVALID", "this enrolment is already terminated")
    enrollment["employment_end_date"] = parsed["employment_end_date"]
    enrollment["enrollment_status"] = "TERMINATED"
    db.touch(enrollment)
    return single(serializers.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/remittance-lines", methods=["GET"])
def list_enrollment_lines(enrollment_id):
    principal = require(ALL_ROLES)
    enrollment = get_enrollment(enrollment_id)
    _enrollment_scope(principal, enrollment)
    status = query_filter("status", LINE_STATUSES)
    rows = [l for l in db.ordered("remittance_lines") if l["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    return paginate(rows, serializers.remittance_line)
