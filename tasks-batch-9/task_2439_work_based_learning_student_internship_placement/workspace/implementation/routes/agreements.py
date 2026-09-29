"""Partnership agreements: negotiation, execution and termination (PRD 3.3)."""

from flask import Blueprint

import derive
from auth import require
from db import by_created, db, new_record, today_str, set_and_touch, touch
from errors import fail
from response import created, listing, ok
from validation import f_bool, f_date, f_str, get_body, pagination, paginate, q_enum, q_str

bp = Blueprint("agreements", __name__)

STATUSES = ("PENDING_EMPLOYER", "PENDING_DISTRICT", "EXECUTED", "TERMINATED", "EXPIRED")
MAX_REVISION_ROUNDS = 3


@bp.post("/agreements")
def draft_agreement():
    user_id, _role = require("WblCoordinator")
    body = get_body()
    # step 7: body foreign keys resolve in declaration order
    partner = derive.get_partner(f_str(body, "employer_partner_id"))
    worksite = derive.get_worksite(f_str(body, "worksite_id"))
    signer = derive.get_supervisor(f_str(body, "employer_signer_supervisor_id"))
    # step 8: body shape
    effective_on = f_date(body, "effective_on")
    expires_on = f_date(body, "expires_on")
    insurance_rider = f_bool(body, "insurance_rider", required=False, default=False)
    if expires_on <= effective_on:
        fail("ERR_INVALID_REQUEST", "Field 'expires_on' must be after 'effective_on'.")
    # step 42: the nominated signer must belong to the agreement's worksite
    if signer["worksite_id"] != worksite["id"]:
        fail("ERR_SUPERVISOR_WORKSITE_MISMATCH",
             "The nominated signer does not belong to the agreement's worksite.")

    agreement = new_record()
    agreement.update({
        "employer_partner_id": partner["id"],
        "worksite_id": worksite["id"],
        "employer_signer_supervisor_id": signer["id"],
        "effective_on": effective_on,
        "expires_on": expires_on,
        "insurance_rider": insurance_rider,
        "revision_round": 0,
        "status": "PENDING_EMPLOYER",
        "created_by_user_id": user_id,
        "executed_by_user_id": None,
        "executed_on": None,
        "change_request_note": None,
        "termination_reason": None,
    })
    db.agreements[agreement["id"]] = agreement
    return created(agreement)


@bp.post("/agreements/<agreementId>/employer-sign")
def employer_sign(agreementId):
    user_id, _role = require("EmployerSupervisor")
    agreement = derive.get_agreement(agreementId)
    # step 3: only the nominated signer may countersign
    if user_id != agreement["employer_signer_supervisor_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the nominated employer signer may countersign this agreement.")
    # step 11
    if agreement["status"] != "PENDING_EMPLOYER":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "The agreement is not awaiting the employer countersignature.")
    # step 25
    worksite = derive.get_worksite(agreement["worksite_id"])
    derive.require_worksite_clearance(worksite)

    agreement["status"] = "PENDING_DISTRICT"
    agreement["change_request_note"] = None
    touch(agreement)
    return ok(agreement)


@bp.post("/agreements/<agreementId>/request-changes")
def request_agreement_changes(agreementId):
    require("WblCoordinator")
    agreement = derive.get_agreement(agreementId)
    body = get_body()
    note = f_str(body, "change_request_note")
    if agreement["status"] != "PENDING_DISTRICT":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "The agreement is not awaiting the district countersignature.")
    if agreement["revision_round"] >= MAX_REVISION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUND_LIMIT",
             "The agreement negotiation loop has consumed its revision cap.")

    agreement["status"] = "PENDING_EMPLOYER"
    agreement["change_request_note"] = note
    agreement["revision_round"] += 1
    touch(agreement)
    return ok(agreement)


@bp.post("/agreements/<agreementId>/execute")
def execute_agreement(agreementId):
    user_id, _role = require("WblCoordinator")
    agreement = derive.get_agreement(agreementId)
    # step 5: an agreement may not be executed by its drafter
    if user_id == agreement["created_by_user_id"]:
        fail("ERR_SELF_EXECUTION_PROHIBITED",
             "The operator who drafted the agreement may not execute it.")
    # step 11
    if agreement["status"] != "PENDING_DISTRICT":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "The agreement is not awaiting the district countersignature.")
    if agreement["insurance_rider"] is not True:
        fail("ERR_INVALID_REQUEST",
             "The agreement cannot be executed without the student-worker insurance rider.")
    partner = db.employer_partners.get(agreement["employer_partner_id"])
    # step 26 then step 35
    derive.require_posture(partner)
    derive.require_workers_comp(partner)

    agreement["status"] = "EXECUTED"
    agreement["executed_by_user_id"] = user_id
    agreement["executed_on"] = today_str()
    touch(agreement)
    return ok(agreement)


@bp.post("/agreements/<agreementId>/terminate")
def terminate_agreement(agreementId):
    require("WblCoordinator")
    agreement = derive.get_agreement(agreementId)
    body = get_body()
    reason = f_str(body, "termination_reason")
    if agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_INVALID_STATE", "Only an executed agreement may be terminated.")

    agreement["status"] = "TERMINATED"
    agreement["termination_reason"] = reason
    touch(agreement)

    for placement in derive.placements_of_agreement(agreement["id"]):
        if placement["lifecycle_status"] not in derive.OPEN_LIFECYCLE:
            continue
        set_and_touch(placement, lifecycle_status="TERMINATED")
        # an agreement termination cancels OPEN/PARTIAL cycles only
        derive.cancel_cycles(placement["id"], ("OPEN", "PARTIAL"))
        derive.release_placement_capacity(placement)

    return ok(agreement)


@bp.get("/agreements/<agreementId>")
def read_agreement(agreementId):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor")
    return ok(derive.get_agreement(agreementId))


@bp.get("/agreements")
def list_agreements():
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor")
    limit, offset = pagination()
    partner_id = q_str("employer_partner_id")
    worksite_id = q_str("worksite_id")
    signer_id = q_str("employer_signer_supervisor_id")
    status = q_enum("status", STATUSES)

    rows = []
    for agreement in db.agreements.values():
        if partner_id is not None and agreement["employer_partner_id"] != partner_id:
            continue
        if worksite_id is not None and agreement["worksite_id"] != worksite_id:
            continue
        if signer_id is not None and agreement["employer_signer_supervisor_id"] != signer_id:
            continue
        if status is not None and agreement["status"] != status:
            continue
        rows.append(agreement)

    page, total = paginate(by_created(rows), limit, offset)
    return listing(page, total, limit, offset)
