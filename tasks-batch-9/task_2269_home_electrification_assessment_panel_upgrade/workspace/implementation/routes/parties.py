"""Contractor and inspector endpoints (PRD section 3.3)."""
from flask import Blueprint

import calc
import clock
import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import (APPLICANT, CONTRACTOR, FIELD_INSPECTOR, PROGRAM_ADMIN,
                    PROGRAM_REVIEWER, authorize)

bp = Blueprint("parties", __name__)


@bp.post("/contractors")
@authorize(CONTRACTOR, PROGRAM_ADMIN)
def create_contractor():
    payload = guards.body()
    record = {
        "program_id": fields.req_str(payload, "program_id", allow_empty=False),
        "business_name": fields.req_str(payload, "business_name", allow_empty=False),
        "license_number": fields.req_str(payload, "license_number", allow_empty=False),
        "license_expires_on": fields.req_date(payload, "license_expires_on"),
        "insurance_expires_on": fields.req_date(payload, "insurance_expires_on"),
        "crew_capacity": fields.opt_int(payload, "crew_capacity", default=2, minimum=1),
    }
    domain.get_program(record["program_id"])
    record.update({
        "status": "PENDING_ENROLLMENT",
        "quality_score_rolling": 100,
        "completed_inspection_count": 0,
        "suspension_reason": None,
        "enrollment_decided_by_user_id": None,
    })
    contractor = store.new_record(record)
    store.contractors[contractor["id"]] = contractor
    return envelope.object_response(store.public(contractor), 201)


@bp.get("/contractors/<contractor_id>")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_contractor(contractor_id):
    contractor = domain.get_contractor(contractor_id)
    return envelope.object_response(store.public(contractor))


@bp.post("/contractors/<contractor_id>/enrollment-decision")
@authorize(PROGRAM_REVIEWER)
def contractor_enrollment_decision(contractor_id):
    payload = guards.body()
    decision = fields.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    fields.opt_str(payload, "decision_notes")
    contractor = domain.get_contractor(contractor_id)

    if contractor["status"] != "PENDING_ENROLLMENT":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)

    contractor["enrollment_decided_by_user_id"] = guards.actor_id()
    if decision == "REJECT":
        contractor["status"] = "ENROLLMENT_REJECTED"
        store.touch(contractor)
        return envelope.object_response(store.public(contractor))

    today = clock.today().isoformat()
    if contractor["license_expires_on"] <= today or contractor["insurance_expires_on"] <= today:
        raise ApiError(errors.ERR_CONTRACTOR_CREDENTIAL_EXPIRED)
    contractor["status"] = "ENROLLED_ACTIVE"
    contractor["quality_score_rolling"] = 100
    store.touch(contractor)
    return envelope.object_response(store.public(contractor))


@bp.post("/contractors/<contractor_id>/suspension")
@authorize(PROGRAM_ADMIN)
def contractor_suspension(contractor_id):
    payload = guards.body()
    action = fields.req_enum(payload, "action", ("SUSPEND", "REINSTATE"))
    fields.opt_str(payload, "suspension_reason")
    contractor = domain.get_contractor(contractor_id)

    if action == "SUSPEND":
        if contractor["status"] != "ENROLLED_ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
        domain.suspend_contractor(contractor, "ADMIN_ACTION")
        return envelope.object_response(store.public(contractor))

    if contractor["status"] != "SUSPENDED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    today = clock.today().isoformat()
    if contractor["license_expires_on"] <= today or contractor["insurance_expires_on"] <= today:
        raise ApiError(errors.ERR_CONTRACTOR_CREDENTIAL_EXPIRED)
    domain.reinstate_contractor(contractor)
    return envelope.object_response(store.public(contractor))


@bp.get("/contractors/<contractor_id>/quality-review")
@authorize(CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def contractor_quality_review(contractor_id):
    contractor = domain.get_contractor(contractor_id)
    program = store.programs.get(contractor["program_id"])
    candidates = calc.quality_candidates(contractor["id"])
    rolling, rolling_count = calc.rolling_window_score(candidates)
    weighted, weighted_count = calc.severity_weighted_score(candidates)
    suspension_threshold = program["quality_suspension_threshold"] if program else 70
    recertification_threshold = program["recertification_threshold"] if program else 75
    return envelope.object_response({
        "contractor_id": contractor["id"],
        "rolling_window_score": rolling,
        "severity_weighted_score": weighted,
        "rolling_window_inspection_count": rolling_count,
        "weighted_inspection_count": weighted_count,
        "suspension_threshold": suspension_threshold,
        "recertification_threshold": recertification_threshold,
        "recertification_eligible": weighted >= recertification_threshold,
    })


@bp.post("/inspectors")
@authorize(PROGRAM_ADMIN)
def create_inspector():
    payload = guards.body()
    record = {
        "program_id": fields.req_str(payload, "program_id", allow_empty=False),
        "inspector_name": fields.req_str(payload, "inspector_name", allow_empty=False),
        "certification_id": fields.req_str(payload, "certification_id", allow_empty=False),
        "certification_expires_on": fields.opt_date(payload, "certification_expires_on"),
    }
    domain.get_program(record["program_id"])
    inspector = store.new_record(record, versioned=False)
    store.inspectors[inspector["id"]] = inspector
    return envelope.object_response(store.public(inspector), 201)


@bp.get("/inspectors/<inspector_id>")
@authorize(FIELD_INSPECTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_inspector(inspector_id):
    inspector = domain.get_inspector(inspector_id)
    return envelope.object_response(store.public(inspector))
