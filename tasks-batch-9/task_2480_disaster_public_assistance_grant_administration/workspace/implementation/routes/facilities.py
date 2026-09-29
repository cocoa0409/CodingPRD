"""Facility endpoints: registration, amendment, screening."""
from flask import Blueprint

from db import db, new_row, now_iso, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.calc import facility_eligibility_screening
from services.constants import FACILITY_TYPES, OWNERSHIPS
from services.ledger import applicant_of_facility
from validate import body, present, v_bool, v_enum, v_id, v_str

bp = Blueprint("facilities", __name__)

AMENDMENT_LOCK_STATUSES = ("VALIDATED", "OBLIGATED", "CLOSEOUT_REQUESTED")


@bp.route(PREFIX + "/facilities", methods=["POST"])
def create_facility():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_owner = payload.get("applicant_id")
    if isinstance(raw_owner, str):
        check_scope(actor, raw_owner)

    applicant_id = v_id(payload, "applicant_id")
    name = v_str(payload, "name")
    facility_type = v_enum(payload, "facility_type", FACILITY_TYPES)
    ownership = v_enum(payload, "ownership", OWNERSHIPS)
    in_active_use = v_bool(payload, "in_active_use", required=False, default=True)
    legal = v_bool(payload, "legal_responsibility_documented", required=False, default=True)
    flood_zone = v_bool(payload, "flood_zone", required=False, default=False)
    prior_flood = v_bool(payload, "prior_disaster_flood_damage", required=False,
                         default=False)

    require("applicants", applicant_id)

    row = new_row("facilities", {
        "applicant_id": applicant_id,
        "name": name,
        "facility_type": facility_type,
        "ownership": ownership,
        "in_active_use": in_active_use,
        "legal_responsibility_documented": legal,
        "flood_zone": flood_zone,
        "prior_disaster_flood_damage": prior_flood,
        "eligibility_status": "PENDING",
        "screening_failure_reason": None,
        "screened_at": None,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/facilities", methods=["GET"])
def list_facilities():
    authenticate(ALL_ROLES)
    return render_list("facilities", {
        "applicant_id": "applicant_id",
        "eligibility_status": "eligibility_status",
        "facility_type": "facility_type",
    })


@bp.route(PREFIX + "/facilities/<facility_id>", methods=["GET"])
def get_facility(facility_id):
    actor = authenticate(ALL_ROLES)
    facility = find("facilities", facility_id)
    if facility is not None:
        check_scope(actor, facility["applicant_id"])
    facility = require("facilities", facility_id)
    return respond(facility)


@bp.route(PREFIX + "/facilities/<facility_id>", methods=["PATCH"])
def amend_facility(facility_id):
    actor = authenticate(("ApplicantAgent",))
    facility = find("facilities", facility_id)
    if facility is not None:
        check_scope(actor, facility["applicant_id"])
    facility = require("facilities", facility_id)

    payload = body()
    in_active_use = v_bool(payload, "in_active_use", required=False, default=None)
    legal = v_bool(payload, "legal_responsibility_documented", required=False,
                   default=None)
    ownership = v_enum(payload, "ownership", OWNERSHIPS, required=False, default=None)
    flood_zone = v_bool(payload, "flood_zone", required=False, default=None)
    prior_flood = v_bool(payload, "prior_disaster_flood_damage", required=False,
                         default=None)

    for project in db.projects.values():
        if project["facility_id"] == facility["id"] \
                and project["status"] in AMENDMENT_LOCK_STATUSES:
            fail("ERR_FACILITY_AMENDMENT_LOCKED",
                 "a project on this facility has passed cost review")

    if in_active_use is not None:
        setf(facility, "in_active_use", in_active_use)
    if legal is not None:
        setf(facility, "legal_responsibility_documented", legal)
    if ownership is not None:
        setf(facility, "ownership", ownership)
    if flood_zone is not None:
        setf(facility, "flood_zone", flood_zone)
    if prior_flood is not None:
        setf(facility, "prior_disaster_flood_damage", prior_flood)

    setf(facility, "eligibility_status", "PENDING")
    setf(facility, "screening_failure_reason", None)
    setf(facility, "screened_at", None)
    touch(facility)
    return respond(facility)


@bp.route(PREFIX + "/facilities/<facility_id>/screen", methods=["POST"])
def screen_facility(facility_id):
    authenticate(("ProgramSpecialist",))
    facility = require("facilities", facility_id)

    if facility["eligibility_status"] != "PENDING":
        fail("ERR_FACILITY_INVALID_STATE",
             "screening is admissible only from PENDING")

    status, reason = facility_eligibility_screening(
        facility, applicant_of_facility(facility)
    )
    setf(facility, "eligibility_status", status)
    setf(facility, "screening_failure_reason", reason)
    setf(facility, "screened_at", now_iso())
    touch(facility)
    return respond(facility)
