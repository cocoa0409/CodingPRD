"""ServiceBay / MobileServiceUnit endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import store, stamp_new, touch
from errors import err_not_found, err_invalid
from helpers import (body, req_str, req_enum, opt_int, paginate, sort_created,
                     apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import service_bay as bay_ser, mobile_service_unit as mu_ser

bp = Blueprint("resources", __name__)

BAY_TYPES = {"STANDARD", "HEAVY_ALIGNMENT"}
RESOURCE_STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}


# ---------- service bays ----------

@bp.post("/dealership/service-bays")
def create_bay():
    caller(["ServiceManager"])
    data = body()
    code = req_str(data, "bay_code")
    btype = req_enum(data, "bay_type", BAY_TYPES)
    open_hour = opt_int(data, "open_hour", 7, minimum=0, maximum=23)
    close_hour = opt_int(data, "close_hour", 19, minimum=1, maximum=24)
    if close_hour <= open_hour:
        raise err_invalid("close_hour must be strictly after open_hour")
    bay = {
        "bay_code": code,
        "bay_type": btype,
        "open_hour": open_hour,
        "close_hour": close_hour,
        "status": "ACTIVE",
    }
    stamp_new(bay)
    store.service_bays[bay["id"]] = bay
    return success(bay_ser(bay), status=201)


@bp.get("/dealership/service-bays")
def list_bays():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.service_bays.values()), [
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([bay_ser(b) for b in page], meta)


@bp.get("/dealership/service-bays/<rid>")
def get_bay(rid):
    caller(ALL_ROLES)
    bay = store.service_bays.get(rid)
    if bay is None:
        raise err_not_found("SERVICE_BAY")
    return success(bay_ser(bay))


@bp.post("/dealership/service-bays/<rid>/set-status")
def set_bay_status(rid):
    caller(["ServiceManager"])
    data = body()
    status = req_enum(data, "status", RESOURCE_STATUSES)
    bay = store.service_bays.get(rid)
    if bay is None:
        raise err_not_found("SERVICE_BAY")
    bay["status"] = status
    touch(bay)
    return success(bay_ser(bay))


# ---------- mobile service units ----------

@bp.post("/dealership/mobile-service-units")
def create_mobile_unit():
    caller(["ServiceManager"])
    data = body()
    code = req_str(data, "unit_code")
    travel = opt_int(data, "default_travel_minutes", 30, minimum=0)
    mu = {
        "unit_code": code,
        "default_travel_minutes": travel,
        "status": "ACTIVE",
    }
    stamp_new(mu)
    store.mobile_service_units[mu["id"]] = mu
    return success(mu_ser(mu), status=201)


@bp.get("/dealership/mobile-service-units")
def list_mobile_units():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.mobile_service_units.values()), [
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([mu_ser(m) for m in page], meta)


@bp.get("/dealership/mobile-service-units/<rid>")
def get_mobile_unit(rid):
    caller(ALL_ROLES)
    mu = store.mobile_service_units.get(rid)
    if mu is None:
        raise err_not_found("MOBILE_SERVICE_UNIT")
    return success(mu_ser(mu))


@bp.post("/dealership/mobile-service-units/<rid>/set-status")
def set_mobile_unit_status(rid):
    caller(["ServiceManager"])
    data = body()
    status = req_enum(data, "status", RESOURCE_STATUSES)
    mu = store.mobile_service_units.get(rid)
    if mu is None:
        raise err_not_found("MOBILE_SERVICE_UNIT")
    mu["status"] = status
    touch(mu)
    return success(mu_ser(mu))
