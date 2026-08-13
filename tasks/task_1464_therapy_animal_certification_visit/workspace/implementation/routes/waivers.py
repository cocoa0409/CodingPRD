"""Liability waiver endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services.records import new_record, touch, public
from util import today, parse_date
from validate import get_body, validate_body

bp = Blueprint("waivers", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_waiver(waiver_id):
    w = store.waivers.get(waiver_id)
    if w is None:
        raise err_not_found("waiver")
    return w


@bp.post("/v1/liability-waivers")
def create_waiver():
    auth = get_auth()
    require_roles(auth, ["Handler"])
    body = validate_body(get_body(), {
        "team_id": ("string", True, None),
        "facility_id": ("string", True, None),
        "waiver_version": ("string", True, None),
        "signed_on": ("date", True, None),
    })
    team = store.teams.get(body["team_id"])
    if team is None:
        raise err_not_found("team")
    facility = store.facilities.get(body["facility_id"])
    if facility is None:
        raise err_not_found("facility")
    if team["handler_id"] != auth.user_id:
        raise err_ownership()
    if parse_date(body["signed_on"]) > today():
        raise err_invalid_request("signed_on may not lie in the future")
    for w in store.waivers.values():
        if (w["team_id"] == team["id"] and w["facility_id"] == facility["id"]
                and w["waiver_version"] == body["waiver_version"] and w["status"] == "SIGNED"):
            raise err("ERR_WAIVER_ALREADY_EXISTS", 422,
                      "A SIGNED waiver already exists for this team/facility/version")
    rec = new_record(store.waivers, {
        "team_id": team["id"],
        "facility_id": facility["id"],
        "waiver_version": body["waiver_version"],
        "signed_on": body["signed_on"],
        "status": "SIGNED",
    })
    return success_object(public(rec), 201)


@bp.get("/v1/liability-waivers/<waiver_id>")
def get_waiver(waiver_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_waiver(waiver_id)), 200)


@bp.get("/v1/liability-waivers")
def list_waivers():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.waivers.values())
    team_id = request.args.get("team_id")
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    if team_id is not None:
        records = [r for r in records if r["team_id"] == team_id]
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/liability-waivers/<waiver_id>/void")
def void_waiver(waiver_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    w = _get_waiver(waiver_id)
    validate_body(get_body(), {"reason": ("string", True, None)})
    if w["status"] != "SIGNED":
        raise err("ERR_WAIVER_NOT_SIGNED", 409, "Waiver is not SIGNED")
    w["status"] = "VOIDED"
    touch(w)
    return success_object(public(w), 200)
