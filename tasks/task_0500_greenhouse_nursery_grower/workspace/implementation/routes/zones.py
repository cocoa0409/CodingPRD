from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  req_str, req_enum, req_int, ApiError, ERR_INVALID_STATE, ERR_ZONE_NOT_EMPTY)

bp = Blueprint("zones", __name__)

READ_ROLES = ["GrowerManager", "ProductionTech", "SalesCoordinator"]
CLIMATE_CLASSES = {"WARM", "COOL", "MIXED"}


@bp.post("/nursery/zones")
def create_zone():
    require(["GrowerManager"])
    body = get_body()
    name = req_str(body, "name")
    climate_class = req_enum(body, "climate_class", CLIMATE_CLASSES)
    capacity_units = req_int(body, "capacity_units", minimum=1)
    z = common_create({
        "name": name,
        "climate_class": climate_class,
        "capacity_units": capacity_units,
        "occupied_units": 0,
        "reserved_units": 0,
        "free_units": capacity_units,
        "fill_state": "OPEN",
        "status": "OPEN_FOR_USE",
    })
    store.zones[z["id"]] = z
    return ok(z, 201)


@bp.get("/nursery/zones/<zid>")
def get_zone(zid):
    require(READ_ROLES)
    z = get_or_404(store.zones, zid)
    return ok(z)


@bp.get("/nursery/zones")
def list_zones():
    require(READ_ROLES)
    rows = list(store.zones.values())
    status = request.args.get("status")
    fill_state = request.args.get("fill_state")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if fill_state is not None:
        rows = [r for r in rows if r["fill_state"] == fill_state]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/nursery/zones/<zid>/batches")
def list_zone_batches(zid):
    require(READ_ROLES)
    get_or_404(store.zones, zid)
    rows = [b for b in store.batches.values() if b["zone_id"] == zid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/nursery/zones/<zid>/quarantine")
def quarantine_zone(zid):
    require(["GrowerManager"])
    z = get_or_404(store.zones, zid)
    if z["status"] != "OPEN_FOR_USE":
        raise ApiError(ERR_INVALID_STATE, "Zone cannot be quarantined from %s" % z["status"])
    z["status"] = "QUARANTINED"
    touch(z)
    return ok(z)


@bp.post("/nursery/zones/<zid>/release-quarantine")
def release_quarantine_zone(zid):
    require(["GrowerManager"])
    z = get_or_404(store.zones, zid)
    if z["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE, "Zone is not quarantined")
    z["status"] = "OPEN_FOR_USE"
    touch(z)
    return ok(z)


@bp.post("/nursery/zones/<zid>/decommission")
def decommission_zone(zid):
    require(["GrowerManager"])
    z = get_or_404(store.zones, zid)
    if z["status"] != "OPEN_FOR_USE":
        raise ApiError(ERR_INVALID_STATE, "Zone cannot be decommissioned from %s" % z["status"])
    if z["occupied_units"] != 0 or z["reserved_units"] != 0:
        raise ApiError(ERR_ZONE_NOT_EMPTY, "Zone still has occupied or reserved units")
    z["status"] = "DECOMMISSIONED"
    touch(z)
    return ok(z)
