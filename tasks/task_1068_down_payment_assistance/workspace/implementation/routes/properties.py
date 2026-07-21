from flask import Blueprint

import store
import context as ctx
from serializers import public
import envelope as env

bp = Blueprint("properties", __name__)

UNIT_TYPES = {"SINGLE_FAMILY", "CONDO", "TOWNHOME"}


@bp.post("/properties")
def create_property():
    ctx.authenticate(["CaseManager"])
    data = ctx.body()
    address = ctx.req_str(data, "address")
    county_code = ctx.req_str(data, "county_code")
    unit_type = ctx.opt_enum(data, "unit_type", UNIT_TYPES, "SINGLE_FAMILY")
    purchase_price_cents = ctx.req_int(data, "purchase_price_cents", 1)

    rec = store.new_record("property")
    rec.update({
        "address": address,
        "county_code": county_code,
        "unit_type": unit_type,
        "purchase_price_cents": purchase_price_cents,
        "appraised_value_cents": None,
    })
    store.properties[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/properties/<pid>")
def get_property(pid):
    ctx.authenticate(["CaseManager", "ClosingCoordinator", "ProgramAdmin"])
    rec = ctx.lookup("property", pid)
    return env.success(public(rec), 200)


@bp.post("/properties/<pid>/appraisal")
def record_appraisal(pid):
    ctx.authenticate(["CaseManager"])
    rec = ctx.lookup("property", pid)
    data = ctx.body()
    appraised = ctx.req_int(data, "appraised_value_cents", 1)
    rec["appraised_value_cents"] = appraised
    store.touch(rec)
    return env.success(public(rec), 200)
