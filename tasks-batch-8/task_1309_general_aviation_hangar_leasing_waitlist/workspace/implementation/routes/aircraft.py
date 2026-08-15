"""LeaseAircraft endpoints: add/list/remove."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_DUPLICATE_N_NUMBER,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PRIMARY_AIRCRAFT_CONFLICT,
)
from routes.leases import get_lease_or_404
from services.core import touch
from timeutil import iso_z
from validators import body, opt_bool, paginate, pagination, req_str

bp = Blueprint("aircraft", __name__)


@bp.post("/leases/<lid>/aircraft")
def add_aircraft(lid):
    uid, _role = require_roles("Tenant")
    lease = get_lease_or_404(lid)
    require_ownership(lease["id"], uid)
    data = body()
    n_number = req_str(data, "n_number")
    make_model = req_str(data, "make_model")
    is_primary = opt_bool(data, "is_primary", False)

    from routes.offers import n_number_in_use
    if n_number_in_use(lease["airport_id"], n_number):
        raise ApiError(ERR_DUPLICATE_N_NUMBER, "n_number already BASED on another active-phase lease at this airport", 422)
    if is_primary:
        for a in db.aircraft.values():
            if a["lease_id"] == lease["id"] and a["status"] == "BASED" and a["is_primary"]:
                raise ApiError(ERR_PRIMARY_AIRCRAFT_CONFLICT, "Lease already has a primary aircraft", 422)

    aircraft = db.new_entity({
        "lease_id": lease["id"],
        "n_number": n_number,
        "make_model": make_model,
        "is_primary": is_primary,
        "removed_at": None,
        "status": "BASED",
    })
    db.aircraft[aircraft["id"]] = aircraft
    return success_obj(db.public(aircraft), 201)


@bp.get("/leases/<lid>/aircraft")
def list_aircraft(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [a for a in db.aircraft.values() if a["lease_id"] == lease["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total)


@bp.post("/aircraft/<aid>/remove")
def remove_aircraft(aid):
    uid, role = require_roles("Tenant", "AirportManager")
    aircraft = db.aircraft.get(aid)
    if aircraft is None:
        raise ApiError(ERR_NOT_FOUND, "Aircraft not found", 404)
    if role == "Tenant":
        require_ownership(aircraft["lease_id"], uid)
    if aircraft["status"] != "BASED":
        raise ApiError(ERR_INVALID_STATE, "Aircraft is not BASED", 409)
    aircraft["status"] = "REMOVED"
    aircraft["removed_at"] = iso_z(db.clock_now())
    touch(aircraft)
    return success_obj(db.public(aircraft), 200)
