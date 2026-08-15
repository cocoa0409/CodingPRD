"""Students, Donors, AwardFunds (PRD §3.1)."""

from flask import Blueprint, g

import db
from errors import raise_err
from middleware import require_roles, body
from response import success
from services import engine
from services.validate import (require_fields, req_string, req_int, req_enum,
                               opt_int, opt_bool, opt_list)

bp = Blueprint("parties", __name__)

MAJORS = {"STEM", "ARTS", "BUSINESS", "HEALTH", "TRADES", "UNDECIDED"}

NONTERMINAL_APP_STATUSES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "SELECTED", "WAITLISTED"}


def _get_student_or_404(sid):
    s = db.get("students", sid)
    if s is None:
        raise_err("ERR_NOT_FOUND", "Student not found")
    return s


def _student_ownership(student):
    if g.role == "Student" and g.user_id != student["id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own record")


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@bp.route("/api/students", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_student():
    data = body()
    require_fields(data, ["full_name", "email", "grade_level", "gpa_hundredths",
                          "residency_state", "intended_major", "household_income_cents",
                          "efc_cents", "cost_of_attendance_cents", "institution_name"])
    full_name = req_string(data, "full_name")
    email = req_string(data, "email")
    grade_level = req_int(data, "grade_level", 9, 12)
    gpa = req_int(data, "gpa_hundredths", 0, 500)
    residency = req_string(data, "residency_state")
    if len(residency) != 2:
        raise_err("ERR_VALIDATION", "residency_state must be a two-letter code")
    major = req_enum(data, "intended_major", MAJORS)
    income = req_int(data, "household_income_cents", 0)
    efc = req_int(data, "efc_cents", 0)
    coa = req_int(data, "cost_of_attendance_cents", 0)
    institution = req_string(data, "institution_name")
    verified = opt_int(data, "verified_gpa_hundredths", 0, 500, default=None)
    tags = opt_list(data, "tags", default=[])

    for other in db.all_records("students"):
        if other["email"] == email:
            raise_err("ERR_VALIDATION", "email must be unique across Students")

    rec = db.create_record("students", {
        "full_name": full_name,
        "email": email,
        "grade_level": grade_level,
        "gpa_hundredths": gpa,
        "verified_gpa_hundredths": verified,
        "residency_state": residency,
        "intended_major": major,
        "household_income_cents": income,
        "efc_cents": efc,
        "cost_of_attendance_cents": coa,
        "institution_name": institution,
        "tags": tags,
        "status": "ACTIVE",
        "total_accepted_cents": 0,
        "total_disbursed_cents": 0,
        "aid_cap_cents": coa - efc,
        "excess_cents": 0,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/students/<sid>", methods=["GET"])
@require_roles("ScholarshipCoordinator", "Student", "FinancialAidOfficer")
def get_student(sid):
    student = _get_student_or_404(sid)
    _student_ownership(student)
    return success(db.serialize(student))


@bp.route("/api/students/<sid>", methods=["PATCH"])
@require_roles("ScholarshipCoordinator")
def patch_student(sid):
    student = _get_student_or_404(sid)
    data = body()
    updates = {}
    if "gpa_hundredths" in data:
        updates["gpa_hundredths"] = opt_int(data, "gpa_hundredths", 0, 500)
    if "verified_gpa_hundredths" in data:
        updates["verified_gpa_hundredths"] = opt_int(data, "verified_gpa_hundredths", 0, 500)
    if "residency_state" in data:
        v = data["residency_state"]
        if not isinstance(v, str) or len(v) != 2:
            raise_err("ERR_VALIDATION", "residency_state must be a two-letter code")
        updates["residency_state"] = v
    if "intended_major" in data:
        if data["intended_major"] not in MAJORS:
            raise_err("ERR_VALIDATION", "invalid intended_major")
        updates["intended_major"] = data["intended_major"]
    if "household_income_cents" in data:
        updates["household_income_cents"] = opt_int(data, "household_income_cents", 0)
    if "efc_cents" in data:
        updates["efc_cents"] = opt_int(data, "efc_cents", 0)
    if "cost_of_attendance_cents" in data:
        updates["cost_of_attendance_cents"] = opt_int(data, "cost_of_attendance_cents", 0)
    if "institution_name" in data:
        v = data["institution_name"]
        if not isinstance(v, str) or not v:
            raise_err("ERR_VALIDATION", "institution_name must be a non-empty string")
        updates["institution_name"] = v
    if "tags" in data:
        updates["tags"] = opt_list(data, "tags", default=[])

    cap_inputs_changed = ("efc_cents" in updates and updates["efc_cents"] != student["efc_cents"]) or \
                         ("cost_of_attendance_cents" in updates and
                          updates["cost_of_attendance_cents"] != student["cost_of_attendance_cents"])
    db.mutate(student, **updates)
    engine.recompute_student(student)
    if cap_inputs_changed:
        engine.stacking_recompute(student)
    return success(db.serialize(student))


@bp.route("/api/students/<sid>/archive", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def archive_student(sid):
    student = _get_student_or_404(sid)
    if student["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Student is not ACTIVE")
    for app in db.all_records("applications"):
        if app["student_id"] == sid and app["status"] in NONTERMINAL_APP_STATUSES:
            raise_err("ERR_INVALID_STATE", "Student has non-terminal applications")
    for a in db.all_records("awards"):
        if a["student_id"] == sid and a["offer_status"] in ("OFFERED", "ACCEPTED"):
            raise_err("ERR_INVALID_STATE", "Student has open awards")
    db.mutate(student, status="ARCHIVED")
    return success(db.serialize(student))


@bp.route("/api/students/<sid>/aid-summary", methods=["GET"])
@require_roles("ScholarshipCoordinator", "Student", "FinancialAidOfficer")
def aid_summary(sid):
    student = _get_student_or_404(sid)
    _student_ownership(student)
    engine.recompute_student(student)
    data = db.serialize(student)
    breakdown = []
    for a in sorted(engine.awards_of_student(sid), key=lambda r: (r["created_at"], r["_seq"])):
        breakdown.append({
            "award_id": a["id"],
            "application_id": a["application_id"],
            "amount_cents": a["amount_cents"],
            "offer_status": a["offer_status"],
            "funding_status": a["funding_status"],
            "net_confirmed_cents": engine.net_confirmed(a["id"]),
        })
    data["awards"] = breakdown
    return success(data)


# ---------------------------------------------------------------------------
# Donors
# ---------------------------------------------------------------------------

@bp.route("/api/donors", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_donor():
    data = body()
    require_fields(data, ["name", "contact_email"])
    name = req_string(data, "name")
    email = req_string(data, "contact_email")
    anonymous = opt_bool(data, "anonymous", False)
    freq = "ANNUAL"
    if "report_frequency" in data and data["report_frequency"] is not None:
        freq = req_enum(data, "report_frequency", {"QUARTERLY", "ANNUAL"})
    rec = db.create_record("donors", {
        "name": name, "contact_email": email,
        "anonymous": anonymous, "report_frequency": freq,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/donors/<did>", methods=["GET"])
@require_roles("ScholarshipCoordinator", "Donor")
def get_donor(did):
    donor = db.get("donors", did)
    if donor is None:
        raise_err("ERR_NOT_FOUND", "Donor not found")
    if g.role == "Donor" and g.user_id != donor["id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Donor may only access own record")
    return success(db.serialize(donor))


# ---------------------------------------------------------------------------
# Award funds
# ---------------------------------------------------------------------------

@bp.route("/api/award-funds", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_fund():
    data = body()
    require_fields(data, ["name"])
    name = req_string(data, "name")
    committed = opt_int(data, "committed_cents", 0, default=0)
    rec = db.create_record("award_funds", {
        "name": name,
        "committed_cents": committed,
        "reserved_cents": 0,
        "disbursed_cents": 0,
        "returned_cents": 0,
        "available_cents": committed,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/award-funds/<fid>", methods=["GET"])
@require_roles("ScholarshipCoordinator", "FinancialAidOfficer")
def get_fund(fid):
    fund = db.get("award_funds", fid)
    if fund is None:
        raise_err("ERR_NOT_FOUND", "AwardFund not found")
    engine.recompute_fund(fund)
    return success(db.serialize(fund))


@bp.route("/api/award-funds/<fid>/commitments", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def add_commitment(fid):
    fund = db.get("award_funds", fid)
    if fund is None:
        raise_err("ERR_NOT_FOUND", "AwardFund not found")
    data = body()
    if "expected_fund_version" not in data:
        raise_err("ERR_VALIDATION", "expected_fund_version is required")
    expected = data["expected_fund_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err("ERR_VALIDATION", "expected_fund_version must be an integer")
    if expected != fund["version"]:
        raise_err("ERR_STALE_VERSION", "Fund version has advanced")
    amount = req_int(data, "amount_cents", 1)
    engine.recompute_fund(fund, committed_override=fund["committed_cents"] + amount)
    return success(db.serialize(fund))
