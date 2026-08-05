"""Operating permits: issue, the two parallel dimensions and admin moves."""
from flask import Blueprint

import calc
import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from store import ordered
from util import add_years, now

bp = Blueprint("operating_permits", __name__)

OP_ACTIONS = ("SUSPEND", "REINSTATE", "REVOKE")


@bp.post("/operating-permits")
def issue_operating_permit():
    authenticate(["HealthOfficer"])
    body = v.body()
    construction_permit = lookup.construction_permit(
        body.get("construction_permit_id"))
    household_size = v.req_int(body, "household_size", minimum=1, maximum=12)

    if construction_permit["status"] != "COMPLETED":
        raise ApiError("ERR_CONSTRUCTION_NOT_COMPLETED")

    design = store.system_designs.get(construction_permit["system_design_id"])
    tank_capacity_gal = design["tank_capacity_gal"] if design else None
    issued_on = now()

    permit = store.new_record()
    permit.update({
        "parcel_id": construction_permit["parcel_id"],
        "construction_permit_id": construction_permit["id"],
        "household_size": household_size,
        "tank_capacity_gal": tank_capacity_gal,
        "issued_on": issued_on,
        "expires_on": add_years(issued_on, calc.OPERATING_PERMIT_TERM_YEARS),
        "last_pumped_on": None,
        "pumping_interval_months": None,
        "next_pumping_due_on": None,
        "monitoring_required": False,
        "status": "ACTIVE",
        "compliance_status": "COMPLIANT",
    })
    months, due = calc.pumping_interval(tank_capacity_gal, household_size,
                                        False, issued_on)
    permit["pumping_interval_months"] = months
    permit["next_pumping_due_on"] = due
    permit["compliance_status"] = calc.pumping_compliance_status(issued_on, due)
    store.operating_permits[permit["id"]] = permit

    parcel = store.parcels.get(permit["parcel_id"])
    if parcel is not None:
        derive.recompute_parcel(parcel)

    return response.ok(serialize.operating_permit(permit), 201)


@bp.get("/operating-permits/<permit_id>")
def read_operating_permit(permit_id):
    authenticate(ALL_ROLES)
    permit = lookup.operating_permit(permit_id)
    return response.ok(serialize.operating_permit(permit))


@bp.get("/operating-permits")
def list_operating_permits():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = ordered(store.operating_permits.values())
    for field in ("parcel_id", "construction_permit_id", "status",
                  "compliance_status"):
        value = v.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("operating_permit", page),
                            limit, offset, total)


@bp.post("/operating-permits/<permit_id>/status")
def set_operating_permit_status(permit_id):
    authenticate(["HealthOfficer"])
    permit = lookup.operating_permit(permit_id)
    body = v.body()
    action = v.req_enum(body, "action", OP_ACTIONS)

    status = permit["status"]
    if action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        derive.set_operating_permit_status(permit, "SUSPENDED")
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        open_orders = [r for r in derive.repair_orders_of_parcel(permit["parcel_id"])
                       if r["status"] in calc.OPEN_REPAIR_STATES]
        if open_orders:
            raise ApiError("ERR_OPEN_REPAIR_ORDER")
        derive.set_operating_permit_status(permit, "ACTIVE")
    else:
        if status not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        derive.set_operating_permit_status(permit, "REVOKED")

    parcel = store.parcels.get(permit["parcel_id"])
    if parcel is not None:
        derive.recompute_parcel(parcel)

    return response.ok(serialize.operating_permit(permit))
