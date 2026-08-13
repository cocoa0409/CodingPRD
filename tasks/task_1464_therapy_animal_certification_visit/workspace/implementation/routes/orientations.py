"""Orientation record endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, err_not_found
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services.records import new_record, touch, public
from util import today, parse_date
from validate import get_body, validate_body

bp = Blueprint("orientations", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_orientation(orientation_id):
    o = store.orientations.get(orientation_id)
    if o is None:
        raise err_not_found("orientation")
    return o


@bp.post("/v1/orientation-records")
def create_orientation():
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    body = validate_body(get_body(), {"team_id": ("string", True, None)})
    team = store.teams.get(body["team_id"])
    if team is None:
        raise err_not_found("team")
    rec = new_record(store.orientations, {
        "team_id": team["id"],
        "facility_id": auth.user_id,  # FacilityCoordinator identity is the Facility id
        "status": "ASSIGNED",
        "attended_on": None,
        "expires_on": None,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/orientation-records/<orientation_id>")
def get_orientation(orientation_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_orientation(orientation_id)), 200)


@bp.get("/v1/orientation-records")
def list_orientations():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.orientations.values())
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


@bp.post("/v1/orientation-records/<orientation_id>/complete")
def complete_orientation(orientation_id):
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    rec = _get_orientation(orientation_id)
    body = validate_body(get_body(), {"attended_on": ("date", True, None)})
    if auth.user_id != rec["facility_id"]:
        raise err_ownership()
    if rec["status"] != "ASSIGNED":
        raise err("ERR_ORIENTATION_NOT_ASSIGNED", 409, "Orientation is not ASSIGNED")
    attended = parse_date(body["attended_on"])
    if attended > today():
        raise err("ERR_ORIENTATION_DATE_FUTURE", 409, "attended_on lies in the future")
    rec["status"] = "COMPLETED"
    rec["attended_on"] = body["attended_on"]
    rec["expires_on"] = (attended + timedelta(days=365)).isoformat()
    touch(rec)
    return success_object(public(rec), 200)


@bp.post("/v1/orientation-records/<orientation_id>/reassign")
def reassign_orientation(orientation_id):
    auth = get_auth()
    require_roles(auth, ["FacilityCoordinator"])
    rec = _get_orientation(orientation_id)
    if auth.user_id != rec["facility_id"]:
        raise err_ownership()
    if rec["status"] != "EXPIRED":
        raise err("ERR_ORIENTATION_NOT_EXPIRED", 409, "Orientation is not EXPIRED")
    rec["status"] = "ASSIGNED"
    rec["attended_on"] = None
    rec["expires_on"] = None
    touch(rec)
    return success_object(public(rec), 200)
