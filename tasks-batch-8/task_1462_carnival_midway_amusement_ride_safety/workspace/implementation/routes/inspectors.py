"""Inspectors: register, read, list, deactivate."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import raise_err, ERR_INSPECTOR_LICENSE_EXISTS
from helpers import get_or_404, paginate, qparam, parse_bool_param
from middleware import authenticate
from response import ok
from validators import get_body, reject_unknown, req_str, req_int

bp = Blueprint("inspectors", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


@bp.post("/inspectors")
def create_inspector():
    authenticate(["StateProgramAdmin"])
    body = get_body()
    reject_unknown(body, {"full_name", "license_number", "max_daily_inspections"})
    full_name = req_str(body, "full_name")
    license_number = req_str(body, "license_number")
    if "max_daily_inspections" in body:
        max_daily = req_int(body, "max_daily_inspections", lo=1, hi=8)
    else:
        max_daily = 3
    for existing in store["inspectors"].values():
        if existing["license_number"] == license_number:
            raise_err(ERR_INSPECTOR_LICENSE_EXISTS, "license_number is already registered")
    inspector = db.register(
        "inspectors",
        {
            "full_name": full_name,
            "license_number": license_number,
            "max_daily_inspections": max_daily,
            "active": True,
        },
    )
    return ok(serialize(inspector), 201)


@bp.get("/inspectors/<iid>")
def get_inspector(iid):
    authenticate(ALL)
    inspector = get_or_404("inspectors", iid)
    return ok(serialize(inspector))


@bp.get("/inspectors")
def list_inspectors():
    authenticate(ALL)
    return paginate("inspectors", {"active": parse_bool_param("active")})


@bp.post("/inspectors/<iid>/deactivate")
def deactivate_inspector(iid):
    authenticate(["StateProgramAdmin"])
    inspector = get_or_404("inspectors", iid)
    body = get_body()
    reject_unknown(body, set())
    if inspector["active"] is not False:
        inspector["active"] = False
        touch(inspector)
    return ok(serialize(inspector))
