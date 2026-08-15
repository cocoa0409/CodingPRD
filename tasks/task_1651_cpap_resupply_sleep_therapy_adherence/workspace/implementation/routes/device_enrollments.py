"""Device enrollment endpoints (PRD 3.2, 3.3, 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ENROLLMENT_NOT_PENDING_SETUP,
    ERR_ENROLLMENT_NOT_READY_FOR_SETUP,
    ERR_ENROLLMENT_NOT_RETRIEVED,
    ERR_PATIENT_NOT_IN_INTAKE,
    ERR_PAYER_POLICY_NOT_FOUND,
    ERR_RENTAL_NOT_IN_RETRIEVAL,
)
from middleware import authorized, ROLE_INTAKE, ROLE_RT
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch, rental_contract_for_enrollment
from util import today, add_months
from validate import (
    get_body,
    req_str,
    req_enum,
    opt_int,
    require_path_resource,
    require_fk,
)

bp = Blueprint("device_enrollments", __name__, url_prefix="/sleep-therapy")

ACQUISITION_TYPES = {"RENTAL", "PURCHASE"}
COMPONENT_TYPES = ("MASK", "CUSHION", "FILTER", "TUBING")


@bp.post("/device-enrollments")
def create_device_enrollment():
    authorized([ROLE_INTAKE])
    body = get_body()

    # Priority 4: body FK existence first.
    patient_id = body.get("patient_id")
    if patient_id is not None:
        require_fk("patients", patient_id, "patient_id")

    if patient_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: patient_id")
    device_serial = req_str(body, "device_serial")
    device_model = req_str(body, "device_model")
    acquisition_type = req_enum(body, "acquisition_type", ACQUISITION_TYPES)

    for existing in db["device_enrollments"].values():
        if existing["device_serial"] == device_serial:
            raise_error(ERR_INVALID_REQUEST, f"device_serial must be unique: {device_serial}")

    rec = new_record("device_enrollments", {
        "patient_id": patient_id,
        "device_serial": device_serial,
        "device_model": device_model,
        "acquisition_type": acquisition_type,
        "enrollment_status": "PENDING_SETUP",
        "setup_completed_on": None,
        "last_adherence_download_on": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/device-enrollments")
def list_device_enrollments():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "enrollment_status": request.args.get("enrollment_status"),
    }
    return list_response("device_enrollments", filters)


@bp.get("/device-enrollments/<rid>")
def get_device_enrollment(rid):
    return get_one("device_enrollments", rid)


@bp.post("/device-enrollments/<rid>/begin-setup")
def begin_setup(rid):
    authorized([ROLE_RT])
    enrollment = require_path_resource("device_enrollments", rid)
    if enrollment["enrollment_status"] != "PENDING_SETUP":
        raise_error(ERR_ENROLLMENT_NOT_PENDING_SETUP,
                    "enrollment must be in PENDING_SETUP to begin setup")
    patient = db["patients"].get(enrollment["patient_id"])
    if patient is None or patient["patient_status"] != "INTAKE":
        raise_error(ERR_PATIENT_NOT_IN_INTAKE, "patient must be in INTAKE for setup")
    enrollment["enrollment_status"] = "SETUP_IN_PROGRESS"
    touch(enrollment)
    return success_object(public(enrollment))


@bp.post("/device-enrollments/<rid>/complete-setup")
def complete_setup(rid):
    authorized([ROLE_RT])
    enrollment = require_path_resource("device_enrollments", rid)
    # PRD 3.3 check order: enrollment state, patient state, payer resolution.
    if enrollment["enrollment_status"] != "SETUP_IN_PROGRESS":
        raise_error(ERR_ENROLLMENT_NOT_READY_FOR_SETUP,
                    "enrollment must be in SETUP_IN_PROGRESS to complete setup")
    patient = db["patients"].get(enrollment["patient_id"])
    if patient is None or patient["patient_status"] != "INTAKE":
        raise_error(ERR_PATIENT_NOT_IN_INTAKE, "patient must be in INTAKE to complete setup")
    payer = db["payer_policies"].get(patient["payer_policy_id"])
    if payer is None:
        raise_error(ERR_PAYER_POLICY_NOT_FOUND, "patient's payer policy does not resolve")

    body = get_body()
    monthly_rental_cents = opt_int(body, "monthly_rental_cents", default=0, minimum=0)

    current = today()

    # Enrollment activation.
    enrollment["enrollment_status"] = "ACTIVE"
    enrollment["setup_completed_on"] = current.isoformat()
    touch(enrollment)

    # Patient activation (single mutation event: all fields, one version bump).
    patient["patient_status"] = "ACTIVE_THERAPY"
    patient["therapy_started_on"] = current.isoformat()
    patient["current_device_enrollment_id"] = enrollment["id"]

    # Seed the four component supply plans (first fill always eligible).
    for component in COMPONENT_TYPES:
        new_record("component_supply_plans", {
            "patient_id": patient["id"],
            "component_type": component,
            "quantity_per_cycle": 1,
            "last_dispensed_on": None,
            "next_eligible_on": None,
            "reminder_sent_on": None,
            "plan_status": "ACTIVE",
        })

    # Rental acquisition spawns a rental contract.
    if enrollment["acquisition_type"] == "RENTAL":
        contract = new_record("rental_contracts", {
            "patient_id": patient["id"],
            "device_enrollment_id": enrollment["id"],
            "payer_policy_id": patient["payer_policy_id"],
            "rental_start_on": current.isoformat(),
            "rental_months_billed": 0,
            "monthly_rental_cents": monthly_rental_cents,
            "billing_status": "SCHEDULED",
            "equipment_status": "WITH_PATIENT",
            "conversion_eligible_on": add_months(
                current, int(payer["rental_months_to_own"])
            ).isoformat(),
        })
        patient["current_rental_contract_id"] = contract["id"]
    touch(patient)

    return success_object(public(enrollment))


@bp.post("/device-enrollments/<rid>/return-to-payer")
def return_to_payer(rid):
    authorized([ROLE_INTAKE])
    enrollment = require_path_resource("device_enrollments", rid)
    if enrollment["enrollment_status"] != "RETRIEVED":
        raise_error(ERR_ENROLLMENT_NOT_RETRIEVED,
                    "enrollment must be in RETRIEVED to return to payer")
    contract = rental_contract_for_enrollment(enrollment["id"])
    if contract is None or contract["equipment_status"] != "RETRIEVED":
        raise_error(ERR_RENTAL_NOT_IN_RETRIEVAL,
                    "linked rental contract's equipment_status must be RETRIEVED")
    enrollment["enrollment_status"] = "RETURNED_TO_PAYER"
    touch(enrollment)
    return success_object(public(enrollment))
