"""Retrieval case endpoints (PRD 3.8): the equipment-recovery chain and the
synchronous discontinuation-finalization cascade on case closure."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_RETRIEVAL_NOT_OPEN,
    ERR_RETRIEVAL_NOT_SCHEDULED,
    ERR_RETRIEVAL_NOT_IN_TRANSIT,
    ERR_RETRIEVAL_NOT_RECEIVED,
    ERR_RETRIEVAL_NOT_CLOSABLE,
    ERR_RETRIEVAL_NOT_OVERDUE,
)
from middleware import authorized, ROLE_INTAKE
from response import success_object
from routes.helpers import get_one, list_response
from services.core import public, touch, cascade_patient_discontinued
from util import today, parse_date
from validate import require_path_resource

bp = Blueprint("retrieval_cases", __name__, url_prefix="/sleep-therapy")


@bp.get("/retrieval-cases")
def list_retrieval_cases():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "device_enrollment_id": request.args.get("device_enrollment_id"),
        "rental_contract_id": request.args.get("rental_contract_id"),
        "retrieval_status": request.args.get("retrieval_status"),
    }
    return list_response("retrieval_cases", filters)


@bp.get("/retrieval-cases/<rid>")
def get_retrieval_case(rid):
    return get_one("retrieval_cases", rid)


@bp.post("/retrieval-cases/<rid>/schedule-pickup")
def schedule_pickup(rid):
    authorized([ROLE_INTAKE])
    case = require_path_resource("retrieval_cases", rid)
    if case["retrieval_status"] != "OPEN":
        raise_error(ERR_RETRIEVAL_NOT_OPEN, "case must be in OPEN to schedule a pickup")
    case["retrieval_status"] = "SCHEDULED"
    touch(case)
    return success_object(public(case))


@bp.post("/retrieval-cases/<rid>/mark-picked-up")
def mark_picked_up(rid):
    authorized([ROLE_INTAKE])
    case = require_path_resource("retrieval_cases", rid)
    if case["retrieval_status"] != "SCHEDULED":
        raise_error(ERR_RETRIEVAL_NOT_SCHEDULED, "case must be in SCHEDULED to mark picked up")
    case["retrieval_status"] = "IN_TRANSIT"
    touch(case)
    return success_object(public(case))


@bp.post("/retrieval-cases/<rid>/mark-received")
def mark_received(rid):
    authorized([ROLE_INTAKE])
    case = require_path_resource("retrieval_cases", rid)
    if case["retrieval_status"] != "IN_TRANSIT":
        raise_error(ERR_RETRIEVAL_NOT_IN_TRANSIT, "case must be in IN_TRANSIT to mark received")

    case["retrieval_status"] = "RECEIVED"
    case["received_on"] = today().isoformat()
    touch(case)

    enrollment = db["device_enrollments"].get(case["device_enrollment_id"])
    if enrollment is not None and enrollment["enrollment_status"] != "RETRIEVED":
        enrollment["enrollment_status"] = "RETRIEVED"
        touch(enrollment)
    if case.get("rental_contract_id"):
        contract = db["rental_contracts"].get(case["rental_contract_id"])
        if contract is not None and contract["equipment_status"] != "RETRIEVED":
            contract["equipment_status"] = "RETRIEVED"
            touch(contract)
    return success_object(public(case))


@bp.post("/retrieval-cases/<rid>/reconcile")
def reconcile(rid):
    authorized([ROLE_INTAKE])
    case = require_path_resource("retrieval_cases", rid)
    if case["retrieval_status"] != "RECEIVED":
        raise_error(ERR_RETRIEVAL_NOT_RECEIVED, "case must be in RECEIVED to reconcile")
    case["retrieval_status"] = "RECONCILED"
    touch(case)
    # Synchronous cascade: DISCONTINUING -> DISCONTINUED; equipment recovered.
    patient = db["patients"].get(case["patient_id"])
    cascade_patient_discontinued(patient, case.get("device_enrollment_id"), recovered=True)
    return success_object(public(case))


@bp.post("/retrieval-cases/<rid>/close-unrecoverable")
def close_unrecoverable(rid):
    authorized([ROLE_INTAKE])
    case = require_path_resource("retrieval_cases", rid)
    if case["retrieval_status"] not in ("OPEN", "SCHEDULED", "IN_TRANSIT"):
        raise_error(ERR_RETRIEVAL_NOT_CLOSABLE,
                    "case must be in OPEN, SCHEDULED, or IN_TRANSIT to close unrecoverable")
    if today() <= parse_date(case["due_on"]):
        raise_error(ERR_RETRIEVAL_NOT_OVERDUE,
                    "case may only be closed unrecoverable after its due date")
    case["retrieval_status"] = "CLOSED_UNRECOVERABLE"
    touch(case)
    # Synchronous cascade: DISCONTINUING -> DISCONTINUED; equipment not recovered.
    patient = db["patients"].get(case["patient_id"])
    cascade_patient_discontinued(patient, case.get("device_enrollment_id"), recovered=False)
    return success_object(public(case))
