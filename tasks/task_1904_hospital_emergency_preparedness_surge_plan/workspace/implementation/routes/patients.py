"""Patient tracking and family reunification."""

from flask import Blueprint, request

from db import clock, store
from domain import (TRIAGE_CATEGORIES, get_or_404, list_response, ser_inquiry,
                    ser_patient, site_census)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_dt, field_enum, field_str, new_entity, require_body, touch

bp = Blueprint("patients", __name__)


# ---------------------------------------------------------------------------
# Patient track records
# ---------------------------------------------------------------------------

@bp.post("/patient-records")
@authorize(["PlanningChief"])
def create_patient():
    body = require_body()
    incident_id = field_str(body, "incident_id", required=True)
    patient_ref = field_str(body, "patient_ref", required=True)
    triage_category = field_enum(body, "triage_category", TRIAGE_CATEGORIES,
                                 required=True)
    arrival_at = field_dt(body, "arrival_at", required=True)

    incident = get_or_404("incidents", incident_id)

    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "patient registration requires an ACTIVATED incident")

    for p in store["patients"].values():
        if p["incident_id"] == incident_id and p["patient_ref"] == patient_ref:
            raise ApiError("ERR_DUPLICATE_PATIENT_REF", 409,
                           "patient_ref already exists on this incident")

    patient = new_entity()
    patient.update({
        "incident_id": incident_id,
        "patient_ref": patient_ref,
        "triage_category": triage_category,
        "arrival_at": arrival_at,
        "status": "TRACKED",
        "transfer_site_id": None,
        "transferred_at": None,
        "discharged_at": None,
        "reunified": False,
    })
    store["patients"][patient["id"]] = patient
    return success(ser_patient(patient), "object", 201)


@bp.get("/patient-records")
@authorize(ALL_ROLES)
def list_patients():
    incident_id = request.args.get("incident_id")
    transfer_site_id = request.args.get("transfer_site_id")
    status = request.args.get("status")
    triage_category = request.args.get("triage_category")

    def predicate(p):
        if incident_id is not None and p["incident_id"] != incident_id:
            return False
        if transfer_site_id is not None and p["transfer_site_id"] != transfer_site_id:
            return False
        if status is not None and p["status"] != status:
            return False
        if triage_category is not None and p["triage_category"] != triage_category:
            return False
        return True

    return list_response("patients", ser_patient, predicate)


@bp.get("/patient-records/<patient_id>")
@authorize(ALL_ROLES)
def get_patient(patient_id):
    return success(ser_patient(get_or_404("patients", patient_id)), "object", 200)


@bp.post("/patient-records/<patient_id>/transfer")
@authorize(["PlanningChief"])
def transfer_patient(patient_id):
    patient = get_or_404("patients", patient_id)
    body = require_body()
    site_id = field_str(body, "site_id", required=True)

    site = get_or_404("sites", site_id)

    if patient["status"] != "TRACKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a TRACKED patient can be transferred")
    if site["status"] != "ACTIVATED":
        raise ApiError("ERR_SITE_NOT_ACTIVATED", 409,
                       "the transfer target site is not ACTIVATED")
    if site_census(site["id"]) >= site["bed_capacity"]:
        raise ApiError("ERR_ACS_AT_CAPACITY", 422,
                       "the target site has no free beds")
    if site["activated_incident_id"] != patient["incident_id"]:
        raise ApiError("ERR_CROSS_INCIDENT_REFERENCE", 422,
                       "the target site serves a different incident")

    patient["status"] = "TRANSFERRED"
    patient["transfer_site_id"] = site_id
    patient["transferred_at"] = clock.now()
    touch(patient)
    return success(ser_patient(patient), "object", 200)


@bp.post("/patient-records/<patient_id>/discharge")
@authorize(["PlanningChief"])
def discharge_patient(patient_id):
    patient = get_or_404("patients", patient_id)
    if patient["status"] not in ("TRACKED", "TRANSFERRED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a TRACKED or TRANSFERRED patient can be discharged")
    patient["status"] = "DISCHARGED"
    patient["discharged_at"] = clock.now()
    touch(patient)
    return success(ser_patient(patient), "object", 200)


# ---------------------------------------------------------------------------
# Family inquiries
# ---------------------------------------------------------------------------

@bp.post("/family-inquiries")
@authorize(["PublicInformationOfficer"])
def create_inquiry():
    body = require_body()
    incident_id = field_str(body, "incident_id", required=True)
    inquirer_name = field_str(body, "inquirer_name", required=True)
    inquirer_phone = field_str(body, "inquirer_phone", required=True)
    sought_patient_ref = field_str(body, "sought_patient_ref", required=True)

    incident = get_or_404("incidents", incident_id)

    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "family inquiries require an ACTIVATED incident")

    inquiry = new_entity()
    inquiry.update({
        "incident_id": incident_id,
        "inquirer_name": inquirer_name,
        "inquirer_phone": inquirer_phone,
        "sought_patient_ref": sought_patient_ref,
        "status": "OPEN",
        "matched_patient_record_id": None,
        "matched_at": None,
        "reunited_at": None,
    })
    store["inquiries"][inquiry["id"]] = inquiry
    return success(ser_inquiry(inquiry), "object", 201)


@bp.get("/family-inquiries")
@authorize(ALL_ROLES)
def list_inquiries():
    incident_id = request.args.get("incident_id")
    matched_patient_record_id = request.args.get("matched_patient_record_id")
    status = request.args.get("status")

    def predicate(q):
        if incident_id is not None and q["incident_id"] != incident_id:
            return False
        if (matched_patient_record_id is not None
                and q["matched_patient_record_id"] != matched_patient_record_id):
            return False
        if status is not None and q["status"] != status:
            return False
        return True

    return list_response("inquiries", ser_inquiry, predicate)


@bp.get("/family-inquiries/<inquiry_id>")
@authorize(ALL_ROLES)
def get_inquiry(inquiry_id):
    return success(ser_inquiry(get_or_404("inquiries", inquiry_id)), "object", 200)


@bp.post("/family-inquiries/<inquiry_id>/match")
@authorize(["PublicInformationOfficer"])
def match_inquiry(inquiry_id):
    inquiry = get_or_404("inquiries", inquiry_id)
    body = require_body()
    patient_record_id = field_str(body, "patient_record_id", required=True)

    record = get_or_404("patients", patient_record_id)

    if inquiry["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an OPEN inquiry can be matched")
    if record["incident_id"] != inquiry["incident_id"]:
        raise ApiError("ERR_CROSS_INCIDENT_REFERENCE", 422,
                       "the patient record belongs to a different incident")
    if record["patient_ref"] != inquiry["sought_patient_ref"]:
        raise ApiError("ERR_PATIENT_REF_MISMATCH", 422,
                       "patient_ref does not match the sought patient reference")
    if record["status"] != "TRACKED":
        raise ApiError("ERR_PATIENT_NOT_TRACKED", 422,
                       "the patient record is not TRACKED")
    for other in store["inquiries"].values():
        if (other["id"] != inquiry["id"] and other["status"] == "MATCHED"
                and other["matched_patient_record_id"] == patient_record_id):
            raise ApiError("ERR_PATIENT_ALREADY_MATCHED", 409,
                           "the patient record is already matched to another inquiry")

    inquiry["status"] = "MATCHED"
    inquiry["matched_patient_record_id"] = patient_record_id
    inquiry["matched_at"] = clock.now()
    touch(inquiry)
    return success(ser_inquiry(inquiry), "object", 200)


@bp.post("/family-inquiries/<inquiry_id>/reunite")
@authorize(["PublicInformationOfficer"])
def reunite_inquiry(inquiry_id):
    inquiry = get_or_404("inquiries", inquiry_id)
    if inquiry["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a MATCHED inquiry can be reunified")
    inquiry["status"] = "REUNITED"
    inquiry["reunited_at"] = clock.now()
    touch(inquiry)

    record = store["patients"].get(inquiry["matched_patient_record_id"])
    if record is not None:
        record["reunified"] = True
    return success(ser_inquiry(inquiry), "object", 200)


@bp.post("/family-inquiries/<inquiry_id>/close-no-match")
@authorize(["PublicInformationOfficer"])
def close_inquiry(inquiry_id):
    inquiry = get_or_404("inquiries", inquiry_id)
    if inquiry["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an OPEN inquiry can be closed with no match")
    inquiry["status"] = "CLOSED_NO_MATCH"
    touch(inquiry)
    return success(ser_inquiry(inquiry), "object", 200)
