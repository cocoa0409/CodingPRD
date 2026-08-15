"""Authorization requests: draft, list, read, submit, determinations (PRD 3.2, 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, next_seq, touch
from errors import (
    raise_error,
    ERR_VALIDATION_FAILED,
    ERR_DOSE_EXCEEDS_MAX,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_BENEFIT_NOT_VERIFIED,
    ERR_MISSING_REQUIRED_CRITERIA,
    ERR_SITE_DETERMINATION_MISSING,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    ALL_ROLES, SITE_TYPES, REQUEST_STATUSES,
    get_patient, get_policy, get_request, policy_for_request,
    list_response, has_verified_benefit,
)
from serializers import serialize
from services.transitions import approve_request
from util import new_id, CLOCK
from validate import get_body, req_str, req_int, req_number, req_enum, opt_str, req_version

bp = Blueprint("auth_requests", __name__)

APPEAL_WINDOW_DAYS = 60
DETERMINATION_OUTCOMES = ["APPROVED", "DENIED", "PENDED"]


@bp.post("/infusion/authorization-requests")
def create_request():
    caller = authorized(["AuthCoordinator"])
    body = get_body()
    patient_id = req_str(body, "patient_id")
    policy_id = req_str(body, "policy_id")
    requested_site_type = req_enum(body, "requested_site_type", sorted(SITE_TYPES))
    requested_dose_mg = req_int(body, "requested_dose_mg")
    patient_weight_kg = req_number(body, "patient_weight_kg")
    supersedes_request_id = opt_str(body, "supersedes_request_id")

    # existence, left to right: patient, policy, superseded request
    get_patient(patient_id)
    policy = get_policy(policy_id)
    if supersedes_request_id is not None:
        get_request(supersedes_request_id)

    # dose safety ceiling
    if requested_dose_mg > int(policy["max_dose_mg"]):
        raise_error(ERR_DOSE_EXCEEDS_MAX,
                    f"requested_dose_mg {requested_dose_mg} exceeds policy max_dose_mg {policy['max_dose_mg']}")

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "patient_id": patient_id,
        "policy_id": policy_id,
        "requested_site_type": requested_site_type,
        "requested_dose_mg": requested_dose_mg,
        "patient_weight_kg": patient_weight_kg,
        "supersedes_request_id": supersedes_request_id,
        "status": "DRAFT",
        "submitted_at": None,
        "pended_at": None,
        "denied_at": None,
        "appeal_deadline": None,
        "auth_valid_from": None,
        "auth_valid_to": None,
        "approved_dose_mg": None,
        "denial_reason": None,
        "created_by_user_id": caller.user_id,
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["authorization_requests"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests")
def list_requests():
    authorized(ALL_ROLES)
    patient_id = request.args.get("patient_id")
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    supersedes_request_id = request.args.get("supersedes_request_id")
    if status is not None and status not in REQUEST_STATUSES:
        raise_error(ERR_VALIDATION_FAILED, f"status must be one of {sorted(REQUEST_STATUSES)}")
    items = list(db["authorization_requests"].values())
    if patient_id is not None:
        items = [r for r in items if r["patient_id"] == patient_id]
    if policy_id is not None:
        items = [r for r in items if r["policy_id"] == policy_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if supersedes_request_id is not None:
        items = [r for r in items if r["supersedes_request_id"] == supersedes_request_id]
    return list_response(items)


@bp.get("/infusion/authorization-requests/<rid>")
def read_request(rid):
    authorized(ALL_ROLES)
    return success_object(serialize(get_request(rid)))


@bp.post("/infusion/authorization-requests/<rid>/submit")
def submit_request(rid):
    authorized(["AuthCoordinator"])
    get_body()
    req = get_request(rid)
    now = CLOCK.now()

    if req["status"] == "DRAFT":
        # gates in order: verified benefit -> accepted criteria -> site determination
        if not has_verified_benefit(req["id"]):
            raise_error(ERR_BENEFIT_NOT_VERIFIED,
                        "submit requires at least one VERIFIED benefit investigation")
        accepted = [c for c in db["criteria_submissions"].values()
                    if c["authorization_request_id"] == req["id"] and c["status"] == "ACCEPTED"]
        if not accepted:
            raise_error(ERR_MISSING_REQUIRED_CRITERIA,
                        "submit requires at least one ACCEPTED criteria submission")
        has_site_det = any(d["authorization_request_id"] == req["id"]
                           for d in db["site_of_care_determinations"].values())
        if not has_site_det:
            raise_error(ERR_SITE_DETERMINATION_MISSING,
                        "submit requires at least one site-of-care determination")
    elif req["status"] == "PENDED":
        # the pend/resubmit cycle: one decisive gate — a fresh ACCEPTED submission
        # created after pended_at
        fresh = [c for c in db["criteria_submissions"].values()
                 if c["authorization_request_id"] == req["id"] and c["status"] == "ACCEPTED"
                 and c["created_at"] > req["pended_at"]]
        if not fresh:
            raise_error(ERR_MISSING_REQUIRED_CRITERIA,
                        "resubmit requires an ACCEPTED criteria submission created after pended_at")
    else:
        raise_error(ERR_INVALID_STATE,
                    f"cannot submit an authorization request in {req['status']}")

    req["status"] = "SUBMITTED"
    req["submitted_at"] = now
    touch(req, now)
    return success_object(serialize(req))


@bp.post("/infusion/authorization-requests/<rid>/determinations")
def record_determination(rid):
    caller = authorized(["MedicalDirector"])
    body = get_body()
    outcome = req_enum(body, "outcome", DETERMINATION_OUTCOMES)
    expected_version = req_version(body, "expected_authorization_version")
    denial_reason = None
    if outcome == "DENIED":
        denial_reason = req_str(body, "denial_reason")

    req = get_request(rid)

    # segregation of duties fires before the stale-version check (PRD 3.4)
    if caller.user_id == req["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the request creator may not record its determination")
    if req["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"determinations require SUBMITTED status, found {req['status']}")
    # OCC runs last of all (validation stage 22)
    if expected_version != req["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"expected_authorization_version {expected_version} does not match "
                    f"current version {req['version']}")

    now = CLOCK.now()
    req["decided_by_user_id"] = caller.user_id
    if outcome == "PENDED":
        req["status"] = "PENDED"
        req["pended_at"] = now
        touch(req, now)
    elif outcome == "APPROVED":
        approve_request(req, now)  # sets status, validity window, approved dose; touches
    else:  # DENIED
        req["status"] = "DENIED"
        req["denied_at"] = now
        req["appeal_deadline"] = now + timedelta(days=APPEAL_WINDOW_DAYS)
        req["denial_reason"] = denial_reason
        touch(req, now)
    return success_object(serialize(req))
