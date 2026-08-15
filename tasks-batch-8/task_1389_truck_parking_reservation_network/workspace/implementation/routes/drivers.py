"""Drivers: registration and read (PRD §3.3)."""
from flask import Blueprint

import auth
import domain
import errors
import services
import util

bp = Blueprint("drivers", __name__)


@bp.post("/drivers")
def register_driver():
    ident = auth.identity()
    auth.require_roles(ident, ("Anonymous",))
    body = util.get_body(required=True)
    util.req_fields(body, ["cdl_number", "full_name"])
    cdl = util.req_str(body, "cdl_number")
    name = util.req_str(body, "full_name")
    for d in domain.all_of("drivers"):
        if d["cdl_number"] == cdl:
            raise errors.validation("cdl_number already registered")
    driver = domain.new_entity("drivers", {
        "cdl_number": cdl,
        "full_name": name,
        "strike_events": [],
        "loyalty_points_balance": 0,
    })
    return util.ok(domain.serialize_driver(driver, services.driver_computed(driver)),
                   status=201)


@bp.get("/drivers/<driver_id>")
def get_driver(driver_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver", "FleetManager", "SiteOperator", "NetworkAdmin"))
    # Driver may read only their own record (ownership before existence).
    if ident.role == "Driver" and ident.user_id != driver_id:
        raise errors.forbidden()
    driver = domain.get("drivers", driver_id)
    if driver is None:
        raise errors.not_found("Driver not found")
    return util.ok(domain.serialize_driver(driver, services.driver_computed(driver)))
