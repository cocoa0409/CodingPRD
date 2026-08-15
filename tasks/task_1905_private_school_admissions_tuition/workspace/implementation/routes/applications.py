"""Application routes: create, submit, issue-contract, decline, withdraw."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.calculations import compute_deposit
from services.helpers import (make_record, get_or_404, ref_or_404,
                              parent_scope_check, application_family_id,
                              sort_created)
from services.lifecycle import (decline_application, withdraw_application, touch,
                                CONTRACT_RESPONSE_DAYS)

bp = Blueprint("applications", __name__)

READ_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer", "Parent")


@bp.post("/admissions/applications")
@require_roles("Parent", "AdmissionOfficer")
def create_application(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "applicant_id": "string",
        "cycle_id": "string",
        "grade_section_id": "string",
        "round": ("enum", ("EARLY", "REGULAR")),
    }, {})
    # Body FK existence (layer 8)
    applicant = ref_or_404(db.applicants, vals["applicant_id"], "Applicant")
    cycle = ref_or_404(db.cycles, vals["cycle_id"], "AdmissionCycle")
    section = ref_or_404(db.grade_sections, vals["grade_section_id"], "GradeSection")
    # Family scope (applies on endpoints accepting Parent)
    parent_scope_check(_uid, _role, applicant["family_id"])
    # Constraint: section must belong to the cycle
    if section["cycle_id"] != cycle["id"]:
        raise errors.err(errors.ERR_GRADE_CYCLE_MISMATCH,
                         "Grade section belongs to a different cycle")
    # One live application per (applicant, cycle)
    for other in db.applications.values():
        if (other["applicant_id"] == applicant["id"]
                and other["cycle_id"] == cycle["id"]
                and other["status"] not in ser.APP_TERMINAL):
            raise errors.err(errors.ERR_DUPLICATE_APPLICATION,
                             "A non-terminal application already exists for this applicant in this cycle")
    # Cross-entity state: cycle must be OPEN to admit new applications
    if cycle["status"] != "OPEN":
        raise errors.err(errors.ERR_CYCLE_NOT_OPEN,
                         "Application creation requires the cycle to be OPEN")
    app = make_record(db.applications, {
        "applicant_id": applicant["id"],
        "cycle_id": cycle["id"],
        "grade_section_id": section["id"],
        "round": vals["round"],
        "status": "DRAFT",
        "submitted_at": None,
        "composite_score": None,
        "preference_points": 0,
        "sibling_verified": False,
        "offer_expires_at": None,
        "promoted_from_waitlist": False,
        "estimated_deposit_cents": None,
    })
    return success(ser.application_view(app), 201)


@bp.get("/admissions/applications")
@require_roles(*READ_ROLES)
def list_applications(_uid, _role):
    cycle_id = request.args.get("cycle_id")
    section_id = request.args.get("grade_section_id")
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    family_id = request.args.get("family_id")
    if _role == "Parent":
        family_id = _uid
    items = []
    for a in db.applications.values():
        if cycle_id is not None and a["cycle_id"] != cycle_id:
            continue
        if section_id is not None and a["grade_section_id"] != section_id:
            continue
        if applicant_id is not None and a["applicant_id"] != applicant_id:
            continue
        if status is not None and a["status"] != status:
            continue
        if family_id is not None and application_family_id(a) != family_id:
            continue
        items.append(a)
    return success_list([ser.application_view(a) for a in sort_created(items)])


@bp.get("/admissions/applications/<applicationId>")
@require_roles(*READ_ROLES)
def get_application(applicationId, _uid, _role):
    app = get_or_404(db.applications, applicationId, "Application")
    parent_scope_check(_uid, _role, application_family_id(app))
    return success(ser.application_view(app))


@bp.post("/admissions/applications/<applicationId>/submit")
@require_roles("Parent", "AdmissionOfficer")
def submit_application(applicationId, _uid, _role):
    app = get_or_404(db.applications, applicationId, "Application")
    parent_scope_check(_uid, _role, application_family_id(app))
    if app["status"] != "DRAFT":
        raise errors.err(errors.ERR_APPLICATION_NOT_DRAFT,
                         "Submit requires the application to be DRAFT")
    cycle = db.cycles[app["cycle_id"]]
    # Cycle phase must still admit this round
    if app["round"] == "EARLY":
        if cycle["status"] != "OPEN":
            raise errors.err(errors.ERR_CYCLE_NOT_OPEN,
                             "EARLY submission requires the cycle to be OPEN")
        deadline = db.parse_iso(cycle["early_deadline_at"])
    else:
        if cycle["status"] not in ("OPEN", "EARLY_CLOSED"):
            raise errors.err(errors.ERR_CYCLE_NOT_OPEN,
                             "REGULAR submission requires the cycle to be OPEN or EARLY_CLOSED")
        deadline = db.parse_iso(cycle["regular_deadline_at"])
    if db.get_clock() > deadline:
        raise errors.err(errors.ERR_ROUND_DEADLINE_PASSED,
                         "The round's submission deadline has passed")
    app["status"] = "SUBMITTED"
    app["submitted_at"] = db.fmt_clock(db.get_clock())
    touch(app)
    return success(ser.application_view(app))


@bp.post("/admissions/applications/<applicationId>/issue-contract")
@require_roles("AdmissionOfficer")
def issue_contract(applicationId, _uid, _role):
    app = get_or_404(db.applications, applicationId, "Application")
    if app["status"] != "OFFERED":
        raise errors.err(errors.ERR_APPLICATION_NOT_OFFERED,
                         "Issue-contract requires the application to be OFFERED")
    exp = db.parse_iso(app["offer_expires_at"])
    if exp is not None and db.get_clock() > exp:
        raise errors.err(errors.ERR_OFFER_EXPIRED,
                         "The offer has expired")
    aid = ser.find_aid_for_application(app["id"])
    if aid is not None and aid["award_status"] != "ACCEPTED":
        raise errors.err(errors.ERR_AID_NOT_FINALIZED,
                         "A linked aid application must have award_status ACCEPTED")
    section = db.grade_sections[app["grade_section_id"]]
    award = aid["final_award_cents"] if aid is not None else 0
    tuition = section["tuition_cents"]
    net = tuition - award
    contract = make_record(db.contracts, {
        "application_id": app["id"],
        "tuition_cents": tuition,
        "award_cents": award,
        "net_tuition_cents": net,
        "deposit_amount_cents": compute_deposit(tuition, award),
        "paid_cents": 0,
        "response_due_at": db.fmt_clock(db.days_later(db.get_clock(), CONTRACT_RESPONSE_DAYS)),
        "created_student_id": None,
        "status": "ISSUED",
    })
    app["status"] = "CONTRACT_ISSUED"
    touch(app)
    return success(ser.contract_view(contract), 201)


@bp.post("/admissions/applications/<applicationId>/decline")
@require_roles("Parent")
def decline(applicationId, _uid, _role):
    app = get_or_404(db.applications, applicationId, "Application")
    parent_scope_check(_uid, _role, application_family_id(app))
    if app["status"] != "OFFERED":
        raise errors.err(errors.ERR_APPLICATION_NOT_OFFERED,
                         "Decline requires the application to be OFFERED")
    decline_application(app)
    return success(ser.application_view(app))


@bp.post("/admissions/applications/<applicationId>/withdraw")
@require_roles("Parent")
def withdraw(applicationId, _uid, _role):
    app = get_or_404(db.applications, applicationId, "Application")
    parent_scope_check(_uid, _role, application_family_id(app))
    if app["status"] in ser.APP_TERMINAL:
        raise errors.err(errors.ERR_APPLICATION_TERMINAL,
                         "Application is already in a terminal state")
    withdraw_application(app)
    return success(ser.application_view(app))
