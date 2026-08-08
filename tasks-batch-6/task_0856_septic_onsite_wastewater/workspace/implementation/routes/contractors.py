"""Contractor licensing."""
from flask import Blueprint

import lookup
import response
import serialize
import store
import validate as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from store import touch
from util import now

bp = Blueprint("contractors", __name__)

LICENSE_CLASSES = ("INSTALLER", "PUMPER", "DUAL")
LICENSE_ACTIONS = ("SUSPEND", "REINSTATE", "REVOKE")


@bp.post("/contractors")
def create_contractor():
    authenticate(["HealthOfficer"])
    body = v.body()
    business_name = v.req_str(body, "business_name")
    license_number = v.req_str(body, "license_number")
    license_class = v.req_enum(body, "license_class", LICENSE_CLASSES)
    license_expires_on = v.req_dt(body, "license_expires_on")
    bond_amount_cents = v.req_int(body, "bond_amount_cents", minimum=0)

    for existing in store.contractors.values():
        if existing["license_number"] == license_number:
            raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER")

    contractor = store.new_record()
    contractor.update({
        "business_name": business_name,
        "license_number": license_number,
        "license_class": license_class,
        "license_expires_on": license_expires_on,
        "bond_amount_cents": bond_amount_cents,
        "status": "ACTIVE",
    })
    store.contractors[contractor["id"]] = contractor
    return response.ok(serialize.contractor(contractor, now()), 201)


@bp.get("/contractors/<contractor_id>")
def read_contractor(contractor_id):
    authenticate(ALL_ROLES)
    contractor = lookup.contractor(contractor_id)
    return response.ok(serialize.contractor(contractor, now()))


@bp.post("/contractors/<contractor_id>/license-status")
def set_license_status(contractor_id):
    authenticate(["HealthOfficer"])
    contractor = lookup.contractor(contractor_id)
    body = v.body()
    action = v.req_enum(body, "action", LICENSE_ACTIONS)

    status = contractor["status"]
    if action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        contractor["status"] = "SUSPENDED"
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        contractor["status"] = "ACTIVE"
    else:
        if status not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        contractor["status"] = "REVOKED"
    touch(contractor)
    return response.ok(serialize.contractor(contractor, now()))
