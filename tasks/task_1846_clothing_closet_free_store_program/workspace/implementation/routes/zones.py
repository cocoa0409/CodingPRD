"""Storage zones: create, read, list, OCC-guarded update (PRD 2.8, 3.6)."""
from flask import Blueprint

import services as svc
from db import stamp_new, store, touch
from errors import ApiError
from middleware import require_roles
from response import ok, ok_list
from routes.items import get_zone_or_404
from util import (
    get_body, opt_enum_filter, page_params, paginate, v_enum, v_int, v_str,
)

bp = Blueprint("zones", __name__)

POSTURES = {"AVAILABLE", "NEAR_FULL", "FULL"}


@bp.post("/closet/storage-zones")
@require_roles("ProgramAdmin")
def create_zone():
    data = get_body()
    zone_code = v_str(data, "zone_code")
    season_policy = v_enum(data, "season_policy", svc.SEASONS)
    capacity = v_int(data, "capacity_items", lo=1)
    if any(z["zone_code"] == zone_code for z in store.zones.values()):
        raise ApiError("ERR_ZONE_CODE_TAKEN", 409, "zone_code is already in use")
    z = stamp_new({
        "zone_code": zone_code,
        "season_policy": season_policy,
        "capacity_items": capacity,
        "current_stock": 0,
    })
    store.zones[z["id"]] = z
    return ok(svc.serialize_zone(z), 201)


@bp.get("/closet/storage-zones/<zid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_zone(zid):
    return ok(svc.serialize_zone(get_zone_or_404(zid)))


@bp.get("/closet/storage-zones")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_zones():
    posture = opt_enum_filter("posture", POSTURES)
    limit, offset = page_params()
    rows = list(store.zones.values())
    if posture is not None:
        rows = [z for z in rows if svc.zone_posture(z) == posture]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_zone(z) for z in page], total, limit, offset)


@bp.patch("/closet/storage-zones/<zid>")
@require_roles("ProgramAdmin")
def update_zone(zid):
    z = get_zone_or_404(zid)
    data = get_body()
    capacity = v_int(data, "capacity_items", required=False, lo=1)
    season_policy = v_enum(data, "season_policy", svc.SEASONS, required=False)
    expected = v_int(data, "expected_zone_version")
    if expected != z["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_zone_version does not match the zone's current version",
        )
    new_capacity = capacity if capacity is not None else z["capacity_items"]
    if new_capacity < z["current_stock"]:
        raise ApiError(
            "ERR_CAPACITY_BELOW_STOCK", 409,
            "capacity_items may not be set below the zone's live current_stock",
        )
    if capacity is not None:
        z["capacity_items"] = capacity
    if season_policy is not None:
        z["season_policy"] = season_policy
    touch(z)
    return ok(svc.serialize_zone(z))
