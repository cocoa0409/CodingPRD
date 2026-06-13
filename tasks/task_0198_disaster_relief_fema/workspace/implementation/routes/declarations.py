"""DisasterDeclaration endpoints — PRD §3.1."""
from flask import Blueprint

from db import STORE, to_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int, req_datetime

bp = Blueprint("declarations", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/declarations", methods=["POST"])
def create_declaration():
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    body = require_body()
    title = req_str(body, "title")
    incident_start = req_datetime(body, "incident_start")
    incident_end = req_datetime(body, "incident_end")
    ihp_max_grant_cents = req_int(body, "ihp_max_grant_cents", minimum=0)
    registration_deadline = req_datetime(body, "registration_deadline")
    if incident_end < incident_start:
        raise ApiError("ERR_INVALID_REQUEST", "incident_end must be >= incident_start.")
    with STORE.lock:
        d = base_entity()
        d.update({
            "title": title,
            "incident_start": to_iso(incident_start),
            "incident_end": to_iso(incident_end),
            "ihp_max_grant_cents": ihp_max_grant_cents,
            "registration_deadline": to_iso(registration_deadline),
            "status": "OPEN",
        })
        STORE.declarations[d["id"]] = d
        return success(serialize(d), status=201)


@bp.route("/disaster-relief/declarations", methods=["GET"])
def list_declarations():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(STORE.declarations.values(), {"status": "status"})
    return success(data, pagination=pg)


@bp.route("/disaster-relief/declarations/<did>", methods=["GET"])
def get_declaration(did):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        d = lookup("declarations", did)
        return success(serialize(d))


@bp.route("/disaster-relief/declarations/<did>/close-registration", methods=["POST"])
def close_registration(did):
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    with STORE.lock:
        d = lookup("declarations", did)
        if d["status"] != "OPEN":
            raise ApiError("ERR_DECLARATION_NOT_OPEN")
        d["status"] = "REGISTRATION_CLOSED"
        touch(d)
        return success(serialize(d))


@bp.route("/disaster-relief/declarations/<did>/close", methods=["POST"])
def close_declaration(did):
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    with STORE.lock:
        d = lookup("declarations", did)
        if d["status"] != "REGISTRATION_CLOSED":
            raise ApiError("ERR_DECLARATION_NOT_REGISTRATION_CLOSED")
        # No IhpCase under this declaration may be DISBURSING
        for case in STORE.ihp_cases.values():
            applicant = STORE.applicants.get(case["applicant_id"])
            if applicant and applicant["declaration_id"] == did and case["status"] == "DISBURSING":
                raise ApiError("ERR_OPEN_DISBURSING_CASES")
        d["status"] = "CLOSED"
        touch(d)
        return success(serialize(d))
