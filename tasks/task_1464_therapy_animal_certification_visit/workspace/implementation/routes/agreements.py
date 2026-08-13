"""Facility agreement endpoints (two-signature handshake)."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import cascades
from services.records import new_record, touch, public
from util import today, parse_date
from validate import get_body, validate_body

bp = Blueprint("agreements", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]

NON_TERMINAL = ("DRAFT", "PENDING_FACILITY_SIGNATURE", "PENDING_PROGRAM_SIGNATURE", "ACTIVE")


def _get_agreement(agreement_id):
    a = store.agreements.get(agreement_id)
    if a is None:
        raise err_not_found("agreement")
    return a


@bp.post("/v1/facility-agreements")
def create_agreement():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    body = validate_body(get_body(), {
        "facility_id": ("string", True, None),
        "start_on": ("date", True, None),
        "end_on": ("date", True, None),
        "agreed_max_visit_minutes": ("integer", True, None),
        "insurance_minimum_cents": ("integer", True, None),
        "terms_version": ("string", True, None),
    })
    facility = store.facilities.get(body["facility_id"])
    if facility is None:
        raise err_not_found("facility")
    if not (parse_date(body["start_on"]) < parse_date(body["end_on"])):
        raise err_invalid_request("start_on must be strictly before end_on")
    for ag in store.agreements.values():
        if ag["facility_id"] == facility["id"] and ag["status"] in NON_TERMINAL:
            raise err("ERR_ACTIVE_AGREEMENT_EXISTS", 422,
                      "Facility already has a non-terminal agreement")
    rec = new_record(store.agreements, {
        "facility_id": facility["id"],
        "start_on": body["start_on"],
        "end_on": body["end_on"],
        "agreed_max_visit_minutes": body["agreed_max_visit_minutes"],
        "insurance_minimum_cents": body["insurance_minimum_cents"],
        "terms_version": body["terms_version"],
        "status": "DRAFT",
        "terminated_reason": None,
    })
    # Bubble-up: first agreement lifts PROSPECT -> ONBOARDING.
    if facility["status"] == "PROSPECT":
        facility["status"] = "ONBOARDING"
        touch(facility)
    return success_object(public(rec), 201)


@bp.get("/v1/facility-agreements/<agreement_id>")
def get_agreement(agreement_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_agreement(agreement_id)), 200)


@bp.get("/v1/facility-agreements")
def list_agreements():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.agreements.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/facility-agreements/<agreement_id>/submit")
def submit_agreement(agreement_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    ag = _get_agreement(agreement_id)
    if ag["status"] != "DRAFT":
        raise err("ERR_AGREEMENT_NOT_DRAFT", 409, "Agreement is not DRAFT")
    ag["status"] = "PENDING_FACILITY_SIGNATURE"
    touch(ag)
    return success_object(public(ag), 200)


@bp.post("/v1/facility-agreements/<agreement_id>/sign-facility")
def sign_facility(agreement_id):
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    ag = _get_agreement(agreement_id)
    # Ownership: the acting coordinator's facility must be the agreement's facility.
    if auth.user_id != ag["facility_id"]:
        raise err_ownership()
    if ag["status"] != "PENDING_FACILITY_SIGNATURE":
        raise err("ERR_AGREEMENT_NOT_AWAITING_FACILITY", 409,
                  "Agreement is not awaiting the facility signature")
    if today() > parse_date(ag["end_on"]):
        raise err("ERR_AGREEMENT_TERM_PASSED", 409, "The agreement term has passed")
    ag["status"] = "PENDING_PROGRAM_SIGNATURE"
    touch(ag)
    return success_object(public(ag), 200)


@bp.post("/v1/facility-agreements/<agreement_id>/sign-program")
def sign_program(agreement_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    ag = _get_agreement(agreement_id)
    if ag["status"] != "PENDING_PROGRAM_SIGNATURE":
        raise err("ERR_AGREEMENT_NOT_AWAITING_PROGRAM", 409,
                  "Agreement is not awaiting the program signature")
    if today() > parse_date(ag["end_on"]):
        raise err("ERR_AGREEMENT_TERM_PASSED", 409, "The agreement term has passed")
    ag["status"] = "ACTIVE"
    touch(ag)
    # Bubble-up: ONBOARDING -> ACTIVE (a SUSPENDED facility stays suspended).
    facility = store.facilities.get(ag["facility_id"])
    if facility is not None and facility["status"] == "ONBOARDING":
        facility["status"] = "ACTIVE"
        touch(facility)
    return success_object(public(ag), 200)


@bp.post("/v1/facility-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin", "FacilityCoordinator"])
    ag = _get_agreement(agreement_id)
    body = validate_body(get_body(), {"reason": ("string", True, None)})
    if auth.role == "FacilityCoordinator" and auth.user_id != ag["facility_id"]:
        raise err_ownership()
    if ag["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement is not ACTIVE")
    cascades.terminate_active_agreement(ag, body["reason"])
    return success_object(public(ag), 200)


@bp.post("/v1/facility-agreements/<agreement_id>/withdraw")
def withdraw_agreement(agreement_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    ag = _get_agreement(agreement_id)
    if ag["status"] not in ("DRAFT", "PENDING_FACILITY_SIGNATURE", "PENDING_PROGRAM_SIGNATURE"):
        raise err("ERR_AGREEMENT_NOT_WITHDRAWABLE", 409,
                  "Agreement is not in a pre-activation state")
    ag["status"] = "WITHDRAWN"
    touch(ag)
    return success_object(public(ag), 200)
