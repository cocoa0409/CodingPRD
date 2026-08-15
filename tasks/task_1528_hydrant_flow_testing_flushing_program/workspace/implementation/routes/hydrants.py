"""Hydrant inventory endpoints: create, list, get, decommission."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_HYDRANT_NOT_FOUND,
    ERR_HYDRANT_NOT_IN_SERVICE,
    ERR_HYDRANT_NUMBER_NOT_UNIQUE,
    ERR_PRIVATE_OWNER_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_ZONE_NOT_FOUND,
    invalid_request,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import hydrant_view
from validation import F, paginate, validate_body, validate_empty_body

bp = Blueprint("hydrants", __name__)


def get_hydrant_or_404(hydrant_id):
    h = db.store.hydrants.get(hydrant_id)
    if h is None:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    return h


@bp.post("/hydrants")
def create_hydrant():
    auth_user, role = auth()
    body = validate_body([
        F("hydrant_number", "str"),
        F("program_id", "str"),
        F("zone_id", "str"),
        F("ownership", "enum", arg={"MUNICIPAL", "PRIVATE"}),
        F("private_owner_id", "str", required=False),
        F("required_fire_flow_gpm", "int"),
        F("outlet_diameter_in", "number", required=False, default=2.5),
        F("discharge_coefficient", "number", required=False, default=0.9),
    ])
    require_role(role, {"ProgramAdmin"})
    # Conditional-required rule (schema layer): private_owner_id present iff PRIVATE
    if body["ownership"] == "PRIVATE" and body["private_owner_id"] is None:
        raise invalid_request("private_owner_id is required when ownership is PRIVATE")
    if body["ownership"] == "MUNICIPAL" and body["private_owner_id"] is not None:
        raise invalid_request("private_owner_id must be absent when ownership is MUNICIPAL")
    # Body FK existence
    if body["program_id"] not in db.store.programs:
        raise not_found(ERR_PROGRAM_NOT_FOUND, "FlushingProgram")
    if body["zone_id"] not in db.store.zones:
        raise not_found(ERR_ZONE_NOT_FOUND, "PressureZone")
    if body["private_owner_id"] is not None and body["private_owner_id"] not in db.store.private_owners:
        raise not_found(ERR_PRIVATE_OWNER_NOT_FOUND, "PrivateOwner")
    # Uniqueness
    for h in db.store.hydrants.values():
        if h["hydrant_number"] == body["hydrant_number"]:
            raise ApiError(ERR_HYDRANT_NUMBER_NOT_UNIQUE, "hydrant_number already registered", 409)
    hydrant = new_base()
    hydrant.update({
        "hydrant_number": body["hydrant_number"],
        "program_id": body["program_id"],
        "zone_id": body["zone_id"],
        "ownership": body["ownership"],
        "private_owner_id": body["private_owner_id"],
        "required_fire_flow_gpm": body["required_fire_flow_gpm"],
        "outlet_diameter_in": body["outlet_diameter_in"],
        "discharge_coefficient": body["discharge_coefficient"],
        "status": "IN_SERVICE",
        "active_outage_id": None,
        "latest_inspection_id": None,
        "last_verified_inspection_date": None,
        "inspection_tier": "CURRENT",
        "provisional_fire_flow_gpm": None,
        "approved_fire_flow_gpm": None,
        "targeted_flush_pending": False,
    })
    db.store.hydrants[hydrant["id"]] = hydrant
    return success_object(hydrant_view(hydrant), code=201)


_HYDRANT_FILTERS = (
    "program_id", "zone_id", "private_owner_id", "status",
    "active_outage_id", "latest_inspection_id",
)


@bp.get("/hydrants")
def list_hydrants():
    auth_any()
    items = list(db.store.hydrants.values())
    for field in _HYDRANT_FILTERS:
        value = request.args.get(field)
        if value is not None:
            items = [h for h in items if h[field] == value]
    page, meta = paginate(items)
    return success_list([hydrant_view(h) for h in page], meta)


@bp.get("/hydrants/<hydrant_id>")
def get_hydrant(hydrant_id):
    auth_any()
    return success_object(hydrant_view(get_hydrant_or_404(hydrant_id)))


@bp.post("/hydrants/<hydrant_id>/decommission")
def decommission_hydrant(hydrant_id):
    auth_user, role = auth()
    validate_empty_body()
    require_role(role, {"ProgramAdmin"})
    hydrant = get_hydrant_or_404(hydrant_id)
    if hydrant["status"] != "IN_SERVICE":
        raise ApiError(ERR_HYDRANT_NOT_IN_SERVICE, "Hydrant must be IN_SERVICE", 409)
    hydrant["status"] = "DECOMMISSIONED"
    touch(hydrant)
    return success_object(hydrant_view(hydrant))
