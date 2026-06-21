"""Applicant endpoints — PRD §3.2."""
from flask import Blueprint

from db import STORE, to_iso, now_dt, parse_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int, req_datetime

bp = Blueprint("applicants", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/applicants", methods=["POST"])
def create_applicant():
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    body = require_body()
    # FK existence (priority 3): declaration must be parseable then exist
    declaration_id = req_str(body, "declaration_id")
    with STORE.lock:
        declaration = lookup("declarations", declaration_id)

        # Registration temporal gate (priority 4): declaration OPEN and on/before deadline
        if declaration["status"] != "OPEN":
            raise ApiError("ERR_REGISTRATION_CLOSED", "Declaration is not OPEN for registration.")
        deadline = parse_iso(declaration["registration_deadline"])
        if now_dt() > deadline:
            raise ApiError("ERR_REGISTRATION_CLOSED", "Registration deadline has passed.")

        # damage_date must parse before incident-period check
        damage_date = req_datetime(body, "damage_date")
        incident_start = parse_iso(declaration["incident_start"])
        incident_end = parse_iso(declaration["incident_end"])
        if damage_date < incident_start or damage_date > incident_end:
            raise ApiError("ERR_DAMAGE_DATE_OUT_OF_PERIOD",
                           "damage_date falls outside the incident period.")

        # Remaining field-level validation (priority 13)
        household_name = req_str(body, "household_name")
        household_size = req_int(body, "household_size", minimum=1)
        annual_income_cents = req_int(body, "annual_income_cents", minimum=0)
        reported_repair_cost_cents = req_int(body, "reported_repair_cost_cents", minimum=0)
        reported_personal_property_cents = req_int(body, "reported_personal_property_cents", minimum=0)
        reported_rental_months = req_int(body, "reported_rental_months", minimum=0)

        a = base_entity()
        a.update({
            "declaration_id": declaration_id,
            "household_name": household_name,
            "household_size": household_size,
            "annual_income_cents": annual_income_cents,
            "damage_date": to_iso(damage_date),
            "reported_repair_cost_cents": reported_repair_cost_cents,
            "reported_personal_property_cents": reported_personal_property_cents,
            "reported_rental_months": reported_rental_months,
            "total_dob_cents": 0,
            "status": "REGISTERED",
        })
        STORE.applicants[a["id"]] = a
        return success(serialize(a), status=201)


@bp.route("/disaster-relief/applicants", methods=["GET"])
def list_applicants():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.applicants.values(),
            {"declaration_id": "declaration_id", "status": "status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        a = lookup("applicants", aid)
        return success(serialize(a))


@bp.route("/disaster-relief/applicants/<aid>/withdraw", methods=["POST"])
def withdraw_applicant(aid):
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    with STORE.lock:
        a = lookup("applicants", aid)
        if a["status"] not in ("REGISTERED", "INSPECTION_SCHEDULED"):
            raise ApiError("ERR_APPLICANT_NOT_WITHDRAWABLE")
        a["status"] = "WITHDRAWN"
        touch(a)
        # Cascade: any SCHEDULED assessment for this applicant -> CANCELLED
        for asm in STORE.assessments.values():
            if asm["applicant_id"] == aid and asm["status"] == "SCHEDULED":
                asm["status"] = "CANCELLED"
                touch(asm)
        return success(serialize(a))
