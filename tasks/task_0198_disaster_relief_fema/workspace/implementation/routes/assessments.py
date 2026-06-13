"""DamageAssessment endpoints — PRD §3.2."""
from datetime import timedelta

from flask import Blueprint

from db import STORE, to_iso, parse_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import (
    require_body, req_str, req_int, req_datetime, req_enum,
)

bp = Blueprint("assessments", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/assessments", methods=["POST"])
def create_assessment():
    _uid, role = get_auth()
    require_roles(role, ["Inspector", "ProgramAdmin"])
    body = require_body()
    # FK existence (priority 3): applicant first, then inspector (declaration order)
    applicant_id = req_str(body, "applicant_id")
    inspector_id = req_str(body, "inspector_id")
    with STORE.lock:
        applicant = lookup("applicants", applicant_id)
        inspector = lookup("inspectors", inspector_id)

        # State precondition (priority 5): applicant REGISTERED
        if applicant["status"] != "REGISTERED":
            raise ApiError("ERR_APPLICANT_NOT_REGISTERED")

        scheduled_start = req_datetime(body, "scheduled_start")
        scheduled_end = req_datetime(body, "scheduled_end")
        if scheduled_end <= scheduled_start:
            raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be after scheduled_start.")

        # Inspector overlap (priority 9): closed interval + travel buffer both sides
        buffer = timedelta(minutes=inspector.get("travel_buffer_minutes", 30))
        for other in STORE.assessments.values():
            if other["inspector_id"] != inspector_id:
                continue
            if other["status"] not in ("SCHEDULED", "INSPECTED"):
                continue
            o_start = parse_iso(other["scheduled_start"])
            o_end = parse_iso(other["scheduled_end"])
            if scheduled_start <= o_end + buffer and o_start <= scheduled_end + buffer:
                raise ApiError("ERR_INSPECTOR_DOUBLE_BOOKED")

        asm = base_entity()
        asm.update({
            "applicant_id": applicant_id,
            "inspector_id": inspector_id,
            "scheduled_start": to_iso(scheduled_start),
            "scheduled_end": to_iso(scheduled_end),
            "habitability": None,
            "verified_repair_cost_cents": None,
            "verified_personal_property_cents": None,
            "verified_rental_months": None,
            "status": "SCHEDULED",
        })
        STORE.assessments[asm["id"]] = asm

        # Applicant advances REGISTERED -> INSPECTION_SCHEDULED
        applicant["status"] = "INSPECTION_SCHEDULED"
        touch(applicant)
        return success(serialize(asm), status=201)


@bp.route("/disaster-relief/assessments", methods=["GET"])
def list_assessments():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.assessments.values(),
            {"applicant_id": "applicant_id", "inspector_id": "inspector_id", "status": "status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/assessments/<asid>", methods=["GET"])
def get_assessment(asid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        asm = lookup("assessments", asid)
        return success(serialize(asm))


@bp.route("/disaster-relief/assessments/<asid>/inspect", methods=["POST"])
def inspect_assessment(asid):
    _uid, role = get_auth()
    require_roles(role, ["Inspector"])
    body = require_body()
    with STORE.lock:
        asm = lookup("assessments", asid)
        if asm["status"] != "SCHEDULED":
            raise ApiError("ERR_ASSESSMENT_NOT_SCHEDULED")
        # All four inspection fields required (ERR_MISSING_REQUIRED_FIELD)
        for f in ("habitability", "verified_repair_cost_cents",
                  "verified_personal_property_cents", "verified_rental_months"):
            if f not in body or body[f] is None:
                raise ApiError("ERR_MISSING_REQUIRED_FIELD", f"Missing inspection field: {f}")
        habitability = req_enum(body, "habitability", {"HABITABLE", "UNINHABITABLE"})
        verified_repair = req_int(body, "verified_repair_cost_cents", minimum=0)
        verified_personal = req_int(body, "verified_personal_property_cents", minimum=0)
        verified_rental_months = req_int(body, "verified_rental_months", minimum=0)

        asm["habitability"] = habitability
        asm["verified_repair_cost_cents"] = verified_repair
        asm["verified_personal_property_cents"] = verified_personal
        asm["verified_rental_months"] = verified_rental_months
        asm["status"] = "INSPECTED"
        touch(asm)

        applicant = STORE.applicants.get(asm["applicant_id"])
        if applicant is not None:
            applicant["status"] = "INSPECTED"
            touch(applicant)
        return success(serialize(asm))


@bp.route("/disaster-relief/assessments/<asid>/verify", methods=["POST"])
def verify_assessment(asid):
    _uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    with STORE.lock:
        asm = lookup("assessments", asid)
        if asm["status"] != "INSPECTED":
            raise ApiError("ERR_ASSESSMENT_NOT_INSPECTED")
        asm["status"] = "VERIFIED"
        touch(asm)
        return success(serialize(asm))


@bp.route("/disaster-relief/assessments/<asid>/cancel", methods=["POST"])
def cancel_assessment(asid):
    _uid, role = get_auth()
    require_roles(role, ["Inspector", "ProgramAdmin"])
    with STORE.lock:
        asm = lookup("assessments", asid)
        if asm["status"] != "SCHEDULED":
            raise ApiError("ERR_ASSESSMENT_NOT_SCHEDULED")
        asm["status"] = "CANCELLED"
        touch(asm)
        return success(serialize(asm))
