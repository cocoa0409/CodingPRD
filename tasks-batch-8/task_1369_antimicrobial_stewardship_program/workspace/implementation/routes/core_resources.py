"""Routes: clock, hospitals, practitioners, patient cases, antimicrobials."""

from flask import Blueprint

import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_clock_regression,
)
from middleware import ALL_ROLES, auth_context, require_role
from response import success_object
from services import core
from services.listing import list_response
from services.serializers import serialize
from util import (
    body_json,
    new_id,
    now_iso,
    clock_has_ms,
    optional_bool,
    optional_int,
    parse_iso,
    require_bool,
    require_enum,
    require_fields,
    require_int,
    require_number,
    require_string,
)

bp = Blueprint("core_resources", __name__)


def get_hospital_or_404(hospital_id):
    hospital = db.hospitals.get(hospital_id)
    if hospital is None:
        raise err_not_found("Hospital not found")
    return hospital


# --- Logical clock --------------------------------------------------------------

@bp.route("/stewardship/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth_context()
    require_role(role, {"StewardshipDirector", "StewardshipAdmin"})
    payload = body_json()
    require_fields(payload, ["hospital_id", "to_iso8601"])
    hospital = get_hospital_or_404(payload["hospital_id"])
    target = parse_iso(payload["to_iso8601"], "to_iso8601")
    current = core.hospital_clock(hospital)
    if target <= current:
        raise err_clock_regression()
    hospital["_clock_ms"] = clock_has_ms(payload["to_iso8601"].strip())
    core.set_hospital_clock(hospital, target)
    core.run_clock_sweeps(hospital)
    hospital["updated_at"] = now_iso()
    return success_object(serialize(hospital))


# --- Hospitals -------------------------------------------------------------------

@bp.route("/stewardship/hospitals", methods=["POST"])
def create_hospital():
    _, role = auth_context()
    require_role(role, {"StewardshipAdmin"})
    payload = body_json()
    require_fields(payload, ["name", "nhsn_facility_id"])
    name = require_string(payload, "name")
    nhsn = require_string(payload, "nhsn_facility_id")
    hospital = {
        "id": new_id(),
        "name": name,
        "nhsn_facility_id": nhsn,
        "dot_review_threshold": optional_int(payload, "dot_review_threshold", 7, minimum=1),
        "iv_to_po_min_iv_hours": optional_int(payload, "iv_to_po_min_iv_hours", 48, minimum=24),
        "antibiogram_min_isolates": optional_int(payload, "antibiogram_min_isolates", 30, minimum=1),
        "restricted_auto_expire_hours": optional_int(payload, "restricted_auto_expire_hours", 72, minimum=1),
    }
    core.stamp_new(hospital)
    core.init_hospital_clock(hospital)
    db.hospitals[hospital["id"]] = hospital
    return success_object(serialize(hospital), status=201)


@bp.route("/stewardship/hospitals/<hid>", methods=["GET"])
def get_hospital(hid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_hospital_or_404(hid)))


@bp.route("/stewardship/hospitals", methods=["GET"])
def list_hospitals():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.hospitals.values(), [])


# --- Practitioners ----------------------------------------------------------------

DISCIPLINES = {"PHYSICIAN", "PHARMACIST", "MICROBIOLOGIST", "INFECTION_PREVENTIONIST"}


def get_practitioner_or_404(pid):
    prac = db.practitioners.get(pid)
    if prac is None:
        raise err_not_found("Practitioner not found")
    return prac


@bp.route("/stewardship/practitioners", methods=["POST"])
def create_practitioner():
    _, role = auth_context()
    require_role(role, {"StewardshipAdmin"})
    payload = body_json()
    require_fields(payload, ["hospital_id", "full_name", "license_no", "discipline"])
    get_hospital_or_404(payload["hospital_id"])
    prac = {
        "id": new_id(),
        "hospital_id": payload["hospital_id"],
        "full_name": require_string(payload, "full_name"),
        "license_no": require_string(payload, "license_no"),
        "discipline": require_enum(payload, "discipline", DISCIPLINES),
        "is_stewardship_member": optional_bool(payload, "is_stewardship_member", False),
        "is_active": True,
        "stewardship_standing": "GOOD",
        "unresolved_noncompliance_count": 0,
    }
    core.stamp_new(prac)
    db.practitioners[prac["id"]] = prac
    return success_object(serialize(prac), status=201)


@bp.route("/stewardship/practitioners/<pid>", methods=["GET"])
def get_practitioner(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_practitioner_or_404(pid)))


@bp.route("/stewardship/practitioners", methods=["GET"])
def list_practitioners():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.practitioners.values(), ["hospital_id", "discipline"])


@bp.route("/stewardship/practitioners/<pid>", methods=["PATCH"])
def patch_practitioner(pid):
    _, role = auth_context()
    require_role(role, {"StewardshipAdmin"})
    prac = get_practitioner_or_404(pid)
    payload = body_json()
    changed = False
    if "is_active" in payload and payload["is_active"] is not None:
        prac["is_active"] = optional_bool(payload, "is_active", prac["is_active"])
        changed = True
    if "is_stewardship_member" in payload and payload["is_stewardship_member"] is not None:
        prac["is_stewardship_member"] = optional_bool(
            payload, "is_stewardship_member", prac["is_stewardship_member"]
        )
        changed = True
    if changed:
        core.touch(prac)
    return success_object(serialize(prac))


# --- Patient cases ------------------------------------------------------------------


def get_patient_or_404(pid):
    patient = db.patient_cases.get(pid)
    if patient is None:
        raise err_not_found("PatientCase not found")
    return patient


@bp.route("/stewardship/patient-cases", methods=["POST"])
def create_patient_case():
    _, role = auth_context()
    require_role(role, {"AttendingPhysician", "IDPharmacist", "StewardshipAdmin"})
    payload = body_json()
    require_fields(
        payload,
        ["hospital_id", "mrn", "admitted_at", "ward", "weight_kg", "renal_function_crcl"],
    )
    get_hospital_or_404(payload["hospital_id"])
    admitted_at = parse_iso(payload["admitted_at"], "admitted_at")
    patient = {
        "id": new_id(),
        "hospital_id": payload["hospital_id"],
        "mrn": require_string(payload, "mrn"),
        "admitted_at": payload["admitted_at"],
        "ward": require_string(payload, "ward"),
        "is_immunocompromised": optional_bool(payload, "is_immunocompromised", False),
        "weight_kg": require_number(payload, "weight_kg", exclusive_minimum=0),
        "renal_function_crcl": require_int(payload, "renal_function_crcl", minimum=0),
        "has_enteral_access": optional_bool(payload, "has_enteral_access", True),
        "status": "ADMITTED",
    }
    _ = admitted_at
    core.stamp_new(patient)
    db.patient_cases[patient["id"]] = patient
    return success_object(serialize(patient), status=201)


@bp.route("/stewardship/patient-cases/<pid>", methods=["GET"])
def get_patient_case(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_patient_or_404(pid)))


@bp.route("/stewardship/patient-cases", methods=["GET"])
def list_patient_cases():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.patient_cases.values(), ["hospital_id", "status"])


@bp.route("/stewardship/patient-cases/<pid>/discharge", methods=["POST"])
def discharge_patient(pid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician"})
    patient = get_patient_or_404(pid)
    hospital = get_hospital_or_404(patient["hospital_id"])
    patient["status"] = "DISCHARGED"
    core.touch(patient)
    for order in db.antibiotic_orders.values():
        if order["patient_case_id"] != patient["id"]:
            continue
        if order["therapy_status"] in ("COMPLETED", "DISCONTINUED"):
            continue
        order["therapy_status"] = "COMPLETED"
        order["stopped_at"] = core.clock_iso(hospital)
        core.touch(order)
    for itv in db.audit_interventions.values():
        order = db.antibiotic_orders.get(itv["antibiotic_order_id"])
        if order is None or order["patient_case_id"] != patient["id"]:
            continue
        if itv["recommendation_status"] in ("DOCUMENTED", "RECOMMENDED"):
            itv["recommendation_status"] = "SUPERSEDED"
            core.touch(itv)
    return success_object(serialize(patient))


# --- Antimicrobials ------------------------------------------------------------------


def get_antimicrobial_or_404(aid):
    drug = db.antimicrobials.get(aid)
    if drug is None:
        raise err_not_found("Antimicrobial not found")
    return drug


@bp.route("/stewardship/antimicrobials", methods=["POST"])
def create_antimicrobial():
    _, role = auth_context()
    require_role(role, {"StewardshipAdmin", "IDPharmacist"})
    payload = body_json()
    require_fields(payload, ["hospital_id", "drug_name", "drug_class", "is_restricted", "has_po_form"])
    get_hospital_or_404(payload["hospital_id"])
    drug = {
        "id": new_id(),
        "hospital_id": payload["hospital_id"],
        "drug_name": require_string(payload, "drug_name"),
        "drug_class": require_string(payload, "drug_class"),
        "is_restricted": require_bool(payload, "is_restricted"),
        "has_po_form": require_bool(payload, "has_po_form"),
        "is_penicillin_class": optional_bool(payload, "is_penicillin_class", False),
        "formulary_status": "ACTIVE",
    }
    core.stamp_new(drug)
    db.antimicrobials[drug["id"]] = drug
    return success_object(serialize(drug), status=201)


@bp.route("/stewardship/antimicrobials/<aid>", methods=["GET"])
def get_antimicrobial(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_antimicrobial_or_404(aid)))


@bp.route("/stewardship/antimicrobials", methods=["GET"])
def list_antimicrobials():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.antimicrobials.values(), ["hospital_id", "is_restricted", "drug_class"])


@bp.route("/stewardship/antimicrobials/<aid>", methods=["PATCH"])
def patch_antimicrobial(aid):
    _, role = auth_context()
    require_role(role, {"StewardshipAdmin", "IDPharmacist"})
    drug = get_antimicrobial_or_404(aid)
    payload = body_json()
    if "formulary_status" in payload and payload["formulary_status"] is not None:
        value = payload["formulary_status"]
        if value not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_request("formulary_status must be ACTIVE or SUSPENDED")
        if value != drug["formulary_status"]:
            drug["formulary_status"] = value
            core.touch(drug)
    return success_object(serialize(drug))
