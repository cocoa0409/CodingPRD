"""Graduation application endpoints: evaluate, issue-diploma."""
from flask import Blueprint, request

import clock
import db
from errors import raise_err
from middleware import route
from response import success_object, success_list
from serializers import ser_graduation_application
from services import core
from services import credits as credits_svc
from validation import get_body, req_enum, opt_string, GRAD_DECISIONS

bp = Blueprint("graduation", __name__)

_CHAIN = (("graduation_application", "app_id", db.graduation_applications),)


def _final_year_enrollment(app):
    for en in db.enrollments.values():
        if (en["student_id"] == app["student_id"]
                and en["academic_year_id"] == app["academic_year_id"]):
            return en
    return None


def _final_year_portfolio(app):
    en = _final_year_enrollment(app)
    if en is None:
        return None
    for pf in db.portfolios.values():
        if pf["enrollment_id"] == en["id"]:
            return pf
    return None


def _latest_accepting_reviewer(portfolio):
    if portfolio is None:
        return None
    accepted = [e for e in db.evaluations.values()
                if e["portfolio_id"] == portfolio["id"]
                and e["overall_outcome"] == "ACCEPTED"]
    if not accepted:
        return None
    accepted.sort(key=lambda e: e["created_at"])
    return accepted[-1]["reviewer_id"]


@bp.route("/graduation-applications", methods=["GET"])
@route(["Registrar", "AcademicDirector", "StateAuditor"])
def list_applications():
    recs = list(db.graduation_applications.values())
    year_id = request.args.get("academic_year_id")
    student_id = request.args.get("student_id")
    if year_id:
        recs = [g for g in recs if g["academic_year_id"] == year_id]
    if student_id:
        recs = [g for g in recs if g["student_id"] == student_id]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_graduation_application(g) for g in page],
                        limit, offset, total)


@bp.route("/graduation-applications/<app_id>", methods=["GET"])
@route(["Parent", "Registrar", "AcademicDirector", "StateAuditor"],
       ownership=("graduation_application", "app_id"), parent_chain=_CHAIN)
def get_application(app_id):
    return success_object(ser_graduation_application(db.graduation_applications[app_id]))


@bp.route("/graduation-applications/<app_id>/evaluate", methods=["POST"])
@route(["AcademicDirector"], parent_chain=_CHAIN)
def evaluate_application(app_id):
    app = db.graduation_applications[app_id]
    body = get_body()
    decision = req_enum(body, "decision", GRAD_DECISIONS)
    notes = opt_string(body, "notes")
    if app["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED applications may be evaluated")

    if decision == "DENY":
        app["status"] = "DENIED"
        app["evaluated_by"] = request.user_id
        app["decision_notes"] = notes
        core.touch(app)
        return success_object(ser_graduation_application(app))

    # APPROVE: full criteria chain in pipeline order (duty gates -> standing ->
    # structural -> fiscal last).
    student = db.students.get(app["student_id"])
    en = _final_year_enrollment(app)
    pf = _final_year_portfolio(app)

    # Segregation of duties: evaluator != reviewer who accepted final portfolio
    accepting_reviewer = _latest_accepting_reviewer(pf)
    if accepting_reviewer is not None and request.user_id == accepting_reviewer:
        raise_err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                  "Evaluator must differ from the accepting portfolio reviewer")

    # Standing gate
    if en is not None and en["compliance_standing"] == "NONCOMPLIANT":
        raise_err("ERR_ENROLLMENT_NONCOMPLIANT",
                  "Final-year enrollment is NONCOMPLIANT")

    # Official credit audit
    if not credits_svc.audit_eligible(student):
        raise_err("ERR_GRADUATION_REQUIREMENTS_UNMET",
                  "Official credit audit failed")

    # Final-year portfolio must be ACCEPTED
    if pf is None or pf["status"] != "ACCEPTED":
        raise_err("ERR_FINAL_PORTFOLIO_NOT_ACCEPTED",
                  "Final-year portfolio is not ACCEPTED")

    # Testing requirement
    if en is not None and en["testing_required"] and not en["testing_satisfied"]:
        raise_err("ERR_TESTING_REQUIREMENT_UNMET",
                  "Final-year testing requirement is unsatisfied")

    # Fiscal gate, last
    family = core.family_of_student(student)
    if family is not None and family["fee_balance_cents"] != 0:
        raise_err("ERR_FEES_UNSETTLED", "Family fee balance must be zero")

    app["status"] = "APPROVED"
    app["evaluated_by"] = request.user_id
    app["decision_notes"] = notes
    core.touch(app)
    return success_object(ser_graduation_application(app))


@bp.route("/graduation-applications/<app_id>/issue-diploma", methods=["POST"])
@route(["AcademicDirector"], parent_chain=_CHAIN)
def issue_diploma(app_id):
    app = db.graduation_applications[app_id]
    if app["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only APPROVED applications may be issued a diploma")
    if app["evaluated_by"] is not None and request.user_id == app["evaluated_by"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                  "Diploma issuer must differ from the evaluator")

    student = db.students.get(app["student_id"])
    year = db.academic_years.get(app["academic_year_id"])

    now_iso = clock.now_iso()
    app["status"] = "DIPLOMA_ISSUED"
    app["diploma_issued_at"] = now_iso
    core.touch(app)

    # Diploma number: DIP-<start year>-<zero-padded 3-digit sequence in issue order>
    start_year = year["start_date"].split("-")[0]
    seq = 1
    for other in sorted(
            (g for g in db.graduation_applications.values()
             if g["academic_year_id"] == app["academic_year_id"]
             and g["status"] == "DIPLOMA_ISSUED" and g["id"] != app["id"]),
            key=lambda g: g["diploma_issued_at"] or ""):
        seq += 1
    student["diploma_number"] = f"DIP-{start_year}-{seq:03d}"
    student["transcript_sealed"] = True
    student["sealed_at"] = now_iso
    core.touch(student)

    en = _final_year_enrollment(app)
    if en is not None and en["enrollment_status"] in ("ACTIVE", "COMPLETED"):
        en["enrollment_status"] = "GRADUATED"
        core.touch(en)

    return success_object(ser_graduation_application(app))
