"""Patients and the payer authorization day ledger."""
import config
import derive
import response
import validation
from db import base_record, insert
from errors import ApiError
from web import (ListResult, ObjectResult, bp, endpoint, get_authorization,
                 get_patient)

AUTH_READ_ROLES = ("UnitCoordinator", "Epileptologist", "PayerReviewer")


@bp.route("/neurodiagnostics/patients", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_patient(user_id, role):
    data = validation.body()
    mrn = validation.req_string(data, "mrn")
    display_name = validation.req_string(data, "display_name")
    risk_tier = validation.req_enum(data, "risk_tier", config.RISK_TIERS)
    patient = base_record("patient")
    patient.update({"mrn": mrn, "display_name": display_name, "risk_tier": risk_tier})
    insert("patients", patient)
    return ObjectResult(patient, 201)


@bp.route("/neurodiagnostics/patients/<patient_id>", methods=["GET"])
@endpoint(roles=config.ROLES)
def read_patient(user_id, role, patient_id):
    return ObjectResult(get_patient(patient_id))


@bp.route("/neurodiagnostics/authorizations", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_authorization(user_id, role):
    data = validation.body()
    patient_id = validation.req_id(data, "patient_id")
    requested_setting = validation.req_enum(data, "requested_setting", config.SETTINGS)
    requested_days = validation.req_int(data, "requested_days", minimum=1)
    get_patient(patient_id)
    authorization = base_record("authorization")
    authorization.update({
        "patient_id": patient_id,
        "requested_setting": requested_setting,
        "requested_days": requested_days,
        "status": "DRAFT",
        "authorized_setting": None,
        "authorized_days": 0,
        "days_reserved": 0,
        "days_consumed": 0,
        "days_available": 0,
        "resubmission_count": 0,
        "payer_note": None,
    })
    insert("authorizations", authorization)
    return ObjectResult(authorization, 201)


@bp.route("/neurodiagnostics/patients/<patient_id>/authorizations", methods=["GET"])
@endpoint(roles=AUTH_READ_ROLES)
def list_patient_authorizations(user_id, role, patient_id):
    from flask import request
    get_patient(patient_id)
    limit, offset = response.read_pagination(request.args)
    records = derive.ordered([a for a in derive.db.authorizations.values()
                              if a["patient_id"] == patient_id])
    return ListResult(records, limit, offset)


@bp.route("/neurodiagnostics/authorizations/<authorization_id>", methods=["GET"])
@endpoint(roles=AUTH_READ_ROLES)
def read_authorization(user_id, role, authorization_id):
    return ObjectResult(get_authorization(authorization_id))


@bp.route("/neurodiagnostics/authorizations/<authorization_id>/submit", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def submit_authorization(user_id, role, authorization_id):
    authorization = get_authorization(authorization_id)
    status = authorization["status"]
    if status not in ("DRAFT", "PENDED"):
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE",
                       "Only a DRAFT or PENDED authorization may be submitted.")
    if status == "PENDED":
        if authorization["resubmission_count"] >= config.MAX_RESUBMISSIONS:
            raise ApiError("ERR_RESUBMISSION_LIMIT",
                           "The resubmission limit for this authorization is reached.")
        authorization["resubmission_count"] += 1
        authorization["status"] = "SUBMITTED"
    else:
        authorization["status"] = "SUBMITTED"
        authorization["payer_note"] = None
    return ObjectResult(authorization)


@bp.route("/neurodiagnostics/authorizations/<authorization_id>/payer-decision",
          methods=["POST"])
@endpoint(roles=("PayerReviewer",), mutating=True)
def payer_decision(user_id, role, authorization_id):
    data = validation.body()
    outcome = validation.req_enum(data, "outcome", config.PAYER_OUTCOMES)
    payer_note = validation.opt_string(data, "payer_note")
    authorized_days = None
    authorized_setting = None
    if outcome == "APPROVE":
        authorized_days = validation.req_int(data, "authorized_days", minimum=1)
        authorized_setting = validation.req_enum(data, "authorized_setting",
                                                 config.SETTINGS)
    authorization = get_authorization(authorization_id)
    if authorization["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE",
                       "Only a SUBMITTED authorization may receive a payer decision.")
    authorization["payer_note"] = payer_note
    if outcome == "APPROVE":
        authorization["status"] = "APPROVED"
        authorization["authorized_setting"] = authorized_setting
        authorization["authorized_days"] = authorized_days
        authorization["days_available"] = authorized_days
        authorization["days_reserved"] = 0
        authorization["days_consumed"] = 0
    elif outcome == "PEND":
        authorization["status"] = "PENDED"
    else:
        authorization["status"] = "DENIED"
    return ObjectResult(authorization)
