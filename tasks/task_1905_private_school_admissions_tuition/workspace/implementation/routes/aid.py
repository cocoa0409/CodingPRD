"""Financial aid application routes."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.calculations import compute_aid_award
from services.helpers import (make_record, get_or_404, ref_or_404,
                              parent_scope_check, aid_family_id, sort_created)
from services.lifecycle import touch

bp = Blueprint("aid", __name__)

READ_ROLES = ("AdmissionDirector", "FinancialAidOfficer", "Parent")


def _tuition_for_aid(aid) -> int:
    app = db.applications[aid["application_id"]]
    section = db.grade_sections[app["grade_section_id"]]
    return section["tuition_cents"]


@bp.post("/admissions/aid-applications")
@require_roles("Parent", "FinancialAidOfficer")
def create_aid(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "application_id": "string",
        "reported_annual_income_cents": "int_nonneg",
        "household_size": "int_pos",
    }, {})
    app = ref_or_404(db.applications, vals["application_id"], "Application")
    parent_scope_check(_uid, _role,
                       db.applicants[app["applicant_id"]]["family_id"])
    if ser.find_aid_for_application(app["id"]) is not None:
        raise errors.err(errors.ERR_DUPLICATE_AID_APPLICATION,
                         "An aid application already exists for this admission application")
    if app["status"] in ser.APP_TERMINAL:
        raise errors.err(errors.ERR_APPLICATION_TERMINAL,
                         "The application is in a terminal state")
    if app["status"] == "DRAFT":
        raise errors.err(errors.ERR_APPLICATION_NOT_SUBMITTED,
                         "The application must be past DRAFT to file for aid")
    cycle = db.cycles[app["cycle_id"]]
    if cycle["status"] not in ("OPEN", "EARLY_CLOSED"):
        raise errors.err(errors.ERR_CYCLE_NOT_OPEN,
                         "The application's cycle is not in an admitting status")
    tuition = _tuition_for_aid_record(app)
    aid = make_record(db.aid_applications, {
        "application_id": app["id"],
        "reported_annual_income_cents": vals["reported_annual_income_cents"],
        "household_size": vals["household_size"],
        "verified_annual_income_cents": None,
        "verified_by_user_id": None,
        "verification_status": "SUBMITTED",
        "provisional_award_cents": compute_aid_award(
            vals["reported_annual_income_cents"], vals["household_size"], tuition),
        "final_award_cents": None,
        "award_status": "PROVISIONAL",
        "appeal_reason": None,
    })
    return success(ser.aid_view(aid), 201)


def _tuition_for_aid_record(app) -> int:
    section = db.grade_sections[app["grade_section_id"]]
    return section["tuition_cents"]


@bp.get("/admissions/aid-applications")
@require_roles(*READ_ROLES)
def list_aid(_uid, _role):
    application_id = request.args.get("application_id")
    award_status = request.args.get("award_status")
    verification_status = request.args.get("verification_status")
    items = []
    for a in db.aid_applications.values():
        if application_id is not None and a["application_id"] != application_id:
            continue
        if award_status is not None and a["award_status"] != award_status:
            continue
        if verification_status is not None and a["verification_status"] != verification_status:
            continue
        if _role == "Parent" and aid_family_id(a) != _uid:
            continue
        items.append(a)
    return success_list([ser.aid_view(a) for a in sort_created(items)])


@bp.get("/admissions/aid-applications/<aidApplicationId>")
@require_roles(*READ_ROLES)
def get_aid(aidApplicationId, _uid, _role):
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    parent_scope_check(_uid, _role, aid_family_id(aid))
    return success(ser.aid_view(aid))


@bp.post("/admissions/aid-applications/<aidApplicationId>/verify")
@require_roles("FinancialAidOfficer")
def verify_aid(aidApplicationId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"verified_annual_income_cents": "int_nonneg"}, {})
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    if aid["verification_status"] != "SUBMITTED":
        raise errors.err(errors.ERR_AID_NOT_SUBMITTED,
                         "Verify requires verification_status SUBMITTED")
    aid["verified_annual_income_cents"] = vals["verified_annual_income_cents"]
    aid["verified_by_user_id"] = _uid
    aid["verification_status"] = "VERIFIED"
    touch(aid)
    return success(ser.aid_view(aid))


@bp.post("/admissions/aid-applications/<aidApplicationId>/resubmit-income")
@require_roles("Parent")
def resubmit_income(aidApplicationId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "reported_annual_income_cents": "int_nonneg",
        "household_size": "int_pos",
    }, {})
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    parent_scope_check(_uid, _role, aid_family_id(aid))
    if aid["award_status"] in ("ACCEPTED", "RELEASED"):
        raise errors.err(errors.ERR_AWARD_LOCKED,
                         "Income may not be resubmitted while the award is ACCEPTED or RELEASED")
    aid["reported_annual_income_cents"] = vals["reported_annual_income_cents"]
    aid["household_size"] = vals["household_size"]
    aid["verification_status"] = "SUBMITTED"
    aid["provisional_award_cents"] = compute_aid_award(
        vals["reported_annual_income_cents"], vals["household_size"],
        _tuition_for_aid(aid))
    touch(aid)
    return success(ser.aid_view(aid))


@bp.post("/admissions/aid-applications/<aidApplicationId>/finalize-award")
@require_roles("FinancialAidOfficer")
def finalize_award(aidApplicationId, _uid, _role):
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    # Segregation of duties (pipeline layer 4)
    if aid["verified_by_user_id"] is not None and _uid == aid["verified_by_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "The verifying officer may not finalize this award")
    if aid["verification_status"] != "VERIFIED":
        raise errors.err(errors.ERR_AID_NOT_VERIFIED,
                         "Finalize requires verification_status VERIFIED")
    if aid["award_status"] != "PROVISIONAL":
        raise errors.err(errors.ERR_AWARD_LOCKED,
                         "Finalize requires award_status PROVISIONAL")
    aid["final_award_cents"] = compute_aid_award(
        aid["verified_annual_income_cents"], aid["household_size"],
        _tuition_for_aid(aid))
    aid["award_status"] = "OFFERED"
    touch(aid)
    return success(ser.aid_view(aid))


@bp.post("/admissions/aid-applications/<aidApplicationId>/accept-award")
@require_roles("Parent")
def accept_award(aidApplicationId, _uid, _role):
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    parent_scope_check(_uid, _role, aid_family_id(aid))
    if aid["award_status"] != "OFFERED":
        raise errors.err(errors.ERR_AWARD_NOT_OFFERED,
                         "Accept requires award_status OFFERED")
    if aid["verification_status"] != "VERIFIED":
        raise errors.err(errors.ERR_AWARD_STALE_VERIFICATION,
                         "Income was resubmitted after finalization; re-verification required")
    app = db.applications[aid["application_id"]]
    cycle = db.cycles[app["cycle_id"]]
    committed = ser.cycle_committed(cycle["id"])
    if committed + aid["final_award_cents"] > ser.pacing_cap(cycle):
        raise errors.err(errors.ERR_AID_PACING_CAP_EXCEEDED,
                         "Acceptance would exceed the cycle's current pacing cap")
    aid["award_status"] = "ACCEPTED"
    touch(aid)
    return success(ser.aid_view(aid))


@bp.post("/admissions/aid-applications/<aidApplicationId>/appeal-award")
@require_roles("Parent")
def appeal_award(aidApplicationId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"appeal_reason": "string"}, {})
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    parent_scope_check(_uid, _role, aid_family_id(aid))
    if aid["award_status"] != "OFFERED":
        raise errors.err(errors.ERR_AWARD_NOT_APPEALABLE,
                         "Appeal requires award_status OFFERED")
    aid["appeal_reason"] = vals["appeal_reason"]
    aid["award_status"] = "APPEALED"
    touch(aid)
    return success(ser.aid_view(aid))


@bp.post("/admissions/aid-applications/<aidApplicationId>/revise-award")
@require_roles("FinancialAidOfficer")
def revise_award(aidApplicationId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"revised_final_amount_cents": "int_nonneg"}, {})
    aid = get_or_404(db.aid_applications, aidApplicationId, "AidApplication")
    # Segregation of duties (pipeline layer 4)
    if aid["verified_by_user_id"] is not None and _uid == aid["verified_by_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "The verifying officer may not revise this award")
    if aid["award_status"] != "APPEALED":
        raise errors.err(errors.ERR_AWARD_NOT_APPEALED,
                         "Revise requires award_status APPEALED")
    tuition = _tuition_for_aid(aid)
    band = int((Decimal("0.90") * Decimal(tuition)).quantize(Decimal("1"),
                                                             rounding=ROUND_HALF_UP))
    if vals["revised_final_amount_cents"] > band:
        raise errors.err(errors.ERR_VALIDATION,
                         "Revised amount must be between 0 and 90% of tuition")
    aid["final_award_cents"] = vals["revised_final_amount_cents"]
    aid["award_status"] = "OFFERED"
    touch(aid)
    return success(ser.aid_view(aid))
