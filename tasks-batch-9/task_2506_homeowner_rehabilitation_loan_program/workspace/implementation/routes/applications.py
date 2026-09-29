"""Rehabilitation case intake, ownership and compliance clearances (PRD 3.2, 3.4)."""

from flask import Blueprint

import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import domain, serializers
from services import constants as C

bp = Blueprint("applications", __name__)

READ_ROLES = middleware.STAFF_ROLES
READ_ONE_ROLES = middleware.STAFF_ROLES + (middleware.APPLICANT,)

LEAD_CLEARANCE_DUAL_STATES = (
    "INSPECTED",
    "WRITEUP_APPROVED",
    "BID_OPEN",
    "BID_FAILED",
    "AWARDED",
)


@bp.post(API_PREFIX + "/applications")
@middleware.roles(middleware.INTAKE_SPECIALIST)
def create_application():
    body = validation.json_body()
    applicant = validation.body_fk(
        body, "applicant_id", db.applicants, errors.ERR_APPLICANT_NOT_FOUND
    )
    validation.field_id(body, "applicant_id")

    address_line1 = validation.field_str(body, "address_line1")
    city = validation.field_str(body, "city")
    state_code = validation.field_str(body, "state_code")
    if len(state_code) != 2 or not state_code.isalpha():
        fail(errors.ERR_INVALID_REQUEST, "Field 'state_code' must be a two-letter code.")
    year_built = validation.field_int(body, "year_built", minimum=1850, maximum=2026)
    assessed_value = validation.field_int(body, "assessed_value_cents", minimum=0)
    senior_lien = validation.field_int(
        body, "senior_lien_balance_cents", required=False, default=0, minimum=0
    )
    historic_district = validation.field_bool(body, "historic_district", default=False)
    occupancy_type = validation.field_enum(body, "occupancy_type", C.OCCUPANCY_TYPES)
    ownership_doc_type = validation.field_enum(
        body, "ownership_doc_type", C.OWNERSHIP_DOC_TYPES
    )

    if applicant["eligibility_status"] == "APPLIED":
        fail(errors.ERR_INCOME_NOT_VERIFIED)
    if applicant["income_category"] not in ("EXTREMELY_LOW", "VERY_LOW", "LOW"):
        fail(errors.ERR_APPLICANT_OVER_INCOME)

    lead_required = year_built < 1978
    historic_required = bool(historic_district)

    row = db.new_row()
    row.update(
        {
            "applicant_id": applicant["id"],
            "program_year_id": applicant["program_year_id"],
            "awarded_contractor_id": None,
            "address_line1": address_line1,
            "city": city,
            "state_code": state_code,
            "year_built": year_built,
            "assessed_value_cents": assessed_value,
            "senior_lien_balance_cents": senior_lien,
            "historic_district": historic_district,
            "occupancy_type": occupancy_type,
            "ownership_doc_type": ownership_doc_type,
            "deed_recorded_date": None,
            "ownership_verification_status": "PENDING",
            "lead_review_required": lead_required,
            "historic_review_required": historic_required,
            "workflow_state": "INTAKE",
            "compliance_posture": domain.initial_posture(lead_required, historic_required),
            "lead_hazard_detected": False,
            "lead_hazard_control_method": "NONE",
            "shpo_review_outcome": None,
            "initial_deficiency_count": 0,
            "warranty_expires_at": None,
        }
    )
    db.applications[row["id"]] = row
    return response.object_response(serializers.application(row), 201)


@bp.post(API_PREFIX + "/applications/<application_id>/verify-ownership")
@middleware.roles(middleware.INTAKE_SPECIALIST)
def verify_ownership(application_id):
    row = validation.path_row(
        db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND
    )
    body = validation.json_body()
    deed_recorded_date = validation.field_datetime(body, "deed_recorded_date")
    title_report_clear = validation.field_bool(body, "title_report_clear", required=True)

    if row["workflow_state"] != "INTAKE":
        fail(errors.ERR_INVALID_STATE, "Ownership has already been decided for this case.")

    if title_report_clear and row["ownership_doc_type"] in C.ACCEPTABLE_DOC_TYPES:
        row["ownership_verification_status"] = "VERIFIED"
        row["deed_recorded_date"] = deed_recorded_date
        row["workflow_state"] = "OWNERSHIP_VERIFIED"
    else:
        row["ownership_verification_status"] = "REJECTED"
        row["deed_recorded_date"] = deed_recorded_date
        row["workflow_state"] = "DENIED"
    db.touch(row)
    return response.object_response(serializers.application(row))


@bp.post(API_PREFIX + "/applications/<application_id>/lead-clearance")
@middleware.roles(middleware.INSPECTOR)
def lead_clearance(application_id):
    row = validation.path_row(
        db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND
    )
    body = validation.json_body()
    completed = validation.field_bool(body, "risk_assessment_completed", required=True)
    method = validation.field_enum(body, "hazard_control_method", C.LEAD_CONTROL_METHODS)

    posture = row["compliance_posture"]
    if posture not in ("DUAL_HOLD", "LEAD_HOLD"):
        fail(errors.ERR_INVALID_STATE, "The lead axis is not awaiting clearance.")
    if not completed:
        fail(errors.ERR_INVALID_STATE, "The lead risk assessment is not complete.")
    if posture == "DUAL_HOLD" and row["workflow_state"] not in LEAD_CLEARANCE_DUAL_STATES:
        fail(errors.ERR_INVALID_STATE, "The case is not far enough along for lead clearance.")

    row["lead_hazard_control_method"] = method
    row["compliance_posture"] = (
        "HISTORIC_HOLD" if posture == "DUAL_HOLD" else "CLEARED_WITH_PROTOCOL"
    )
    db.touch(row)
    return response.object_response(serializers.application(row))


@bp.post(API_PREFIX + "/applications/<application_id>/historic-clearance")
@middleware.roles(middleware.PROGRAM_MANAGER)
def historic_clearance(application_id):
    row = validation.path_row(
        db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND
    )
    body = validation.json_body()
    outcome = validation.field_enum(body, "shpo_review_outcome", C.SHPO_OUTCOMES)

    posture = row["compliance_posture"]
    if posture not in ("HISTORIC_HOLD", "DUAL_HOLD"):
        fail(errors.ERR_INVALID_STATE, "The historic axis is not awaiting a determination.")

    row["shpo_review_outcome"] = outcome
    if outcome == "ADVERSE_EFFECT":
        row["compliance_posture"] = "ADVERSE_EFFECT_BLOCKED"
    elif posture == "DUAL_HOLD":
        row["compliance_posture"] = "LEAD_HOLD"
    elif row["lead_review_required"]:
        row["compliance_posture"] = "CLEARED_WITH_PROTOCOL"
    else:
        row["compliance_posture"] = "CLEAR"
    db.touch(row)
    return response.object_response(serializers.application(row))


@bp.get(API_PREFIX + "/applications/<application_id>")
@middleware.roles(*READ_ONE_ROLES)
def read_application(application_id):
    middleware.scope_application(application_id)
    row = validation.path_row(
        db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND
    )
    return response.object_response(serializers.application(row))


@bp.get(API_PREFIX + "/applications")
@middleware.roles(*READ_ROLES)
def list_applications():
    applicant_id = validation.filter_str("applicant_id")
    program_year_id = validation.filter_str("program_year_id")
    contractor_id = validation.filter_str("awarded_contractor_id")
    workflow_state = validation.filter_enum("workflow_state", C.WORKFLOW_STATES)
    posture = validation.filter_enum("compliance_posture", C.COMPLIANCE_POSTURES)
    rows = []
    for row in db.applications.values():
        if applicant_id is not None and row["applicant_id"] != applicant_id:
            continue
        if program_year_id is not None and row["program_year_id"] != program_year_id:
            continue
        if contractor_id is not None and row["awarded_contractor_id"] != contractor_id:
            continue
        if workflow_state is not None and row["workflow_state"] != workflow_state:
            continue
        if posture is not None and row["compliance_posture"] != posture:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.application)
