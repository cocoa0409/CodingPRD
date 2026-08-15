"""Patient endpoints (PRD 3.2, 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_DISCONTINUABLE,
)
from middleware import authorized, ROLE_INTAKE, ROLE_RT
from response import success_object
from routes.helpers import get_one, list_response, serialize
from services.core import (
    new_record,
    touch,
    plans_of_patient,
    current_rental_contract,
)
from util import today, add_days
from validate import get_body, req_str, req_date, require_path_resource, require_fk

bp = Blueprint("patients", __name__, url_prefix="/sleep-therapy")

DISCONTINUATION_REASONS = {
    "THERAPY_DISCONTINUED",
    "PROLONGED_NON_COMPLIANCE",
    "PAYER_STOPPED_COVERAGE",
    "PATIENT_REQUEST",
}


@bp.post("/patients")
def create_patient():
    authorized([ROLE_INTAKE])
    body = get_body()

    # Priority 4: body-referenced FK existence runs before body-shape checks.
    payer_policy_id = body.get("payer_policy_id")
    if payer_policy_id is not None:
        require_fk("payer_policies", payer_policy_id, "payer_policy_id")

    # Priority 27: malformed body surfaces only when no earlier check failed.
    full_name = req_str(body, "full_name")
    date_of_birth = req_date(body, "date_of_birth")
    if payer_policy_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: payer_policy_id")
    npi = req_str(body, "prescribing_clinician_npi")
    if not (npi.isdigit() and len(npi) == 10):
        raise_error(ERR_INVALID_REQUEST, "prescribing_clinician_npi must be a 10-digit NPI")

    rec = new_record("patients", {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "payer_policy_id": payer_policy_id,
        "prescribing_clinician_npi": npi,
        "patient_status": "INTAKE",
        "therapy_started_on": None,
        "adherence_percentage": None,
        "is_compliance_current": False,
        "outstanding_balance_cents": 0,
        "current_device_enrollment_id": None,
        "current_rental_contract_id": None,
    })
    return success_object(serialize("patients", rec), status=201)


@bp.get("/patients")
def list_patients():
    filters = {
        "patient_status": request.args.get("patient_status"),
        "payer_policy_id": request.args.get("payer_policy_id"),
        "current_device_enrollment_id": request.args.get("current_device_enrollment_id"),
        "current_rental_contract_id": request.args.get("current_rental_contract_id"),
    }
    return list_response("patients", filters)


@bp.get("/patients/<rid>")
def get_patient(rid):
    return get_one("patients", rid)


@bp.post("/patients/<rid>/initiate-discontinuation")
def initiate_discontinuation(rid):
    authorized([ROLE_RT])
    patient = require_path_resource("patients", rid)

    # State check precedes body validation (PRD 2.7).
    if patient["patient_status"] not in ("ACTIVE_THERAPY", "NON_COMPLIANT_HOLD"):
        raise_error(
            ERR_PATIENT_NOT_DISCONTINUABLE,
            "patient must be in ACTIVE_THERAPY or NON_COMPLIANT_HOLD to discontinue",
        )
    body = get_body()
    reason = body.get("reason_code")
    if not isinstance(reason, str) or reason not in DISCONTINUATION_REASONS:
        raise_error(ERR_INVALID_REQUEST, "missing or invalid enum field: reason_code")

    current = today()
    patient["patient_status"] = "DISCONTINUING"
    touch(patient)

    for plan in plans_of_patient(patient["id"]):
        if plan["plan_status"] != "CLOSED":
            plan["plan_status"] = "SUSPENDED_DISCONTINUATION"
            touch(plan)

    # When an active rental contract exists, open a retrieval case and move the
    # contract's equipment dimension plus the enrollment.
    contract = current_rental_contract(patient)
    if contract is not None and contract["billing_status"] in (
        "SCHEDULED",
        "BILLING",
        "PAUSED_NON_COMPLIANCE",
    ):
        enrollment_id = contract["device_enrollment_id"]
        new_record("retrieval_cases", {
            "patient_id": patient["id"],
            "device_enrollment_id": enrollment_id,
            "rental_contract_id": contract["id"],
            "reason_code": "THERAPY_DISCONTINUED",
            "retrieval_status": "OPEN",
            "due_on": add_days(current, 14).isoformat(),
            "received_on": None,
        })
        contract["equipment_status"] = "RETRIEVAL_REQUESTED"
        touch(contract)
        enrollment = db["device_enrollments"].get(enrollment_id)
        if enrollment is not None and enrollment["enrollment_status"] == "ACTIVE":
            enrollment["enrollment_status"] = "RETRIEVAL_PENDING"
            touch(enrollment)

    return success_object(serialize("patients", patient))
