"""Clock, Formulation, MixingVessel, DryRoom endpoints."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_FORMULATION_INVALID_STATE,
    ERR_FORMULATION_HAS_INFLIGHT_BATCHES,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, f_num, f_bool, f_enum, f_dt, fmt_dt,
)
from services import (
    new_entity, touch, get_formulation, get_vessel, get_dry_room,
    ser_formulation, ser_vessel, ser_dry_room, sorted_rows, sweep_clock,
    BATCH_INFLIGHT,
)

bp = Blueprint("core", __name__)

CHEMISTRY_FAMILIES = ["EPOXY", "POLYURETHANE", "SILICONE", "ACRYLIC"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    b = body_json()
    raw = b.get("to_iso8601")
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: to_iso8601", 400)
    from helpers import parse_dt
    dt = parse_dt(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field to_iso8601 must be a valid ISO 8601 instant", 400)
    store.clock = dt
    sweep_clock()
    return ok({"current_utc": fmt_dt(store.clock)}, 200)


# ---------------------------------------------------------------------------
# Formulation
# ---------------------------------------------------------------------------

@bp.post("/api/formulations")
@require_roles("PlantManager")
def create_formulation():
    b = body_json()
    code = f_str(b, "code")
    name = f_str(b, "name")
    family = f_enum(b, "chemistry_family", CHEMISTRY_FAMILIES)
    moisture = f_bool(b, "moisture_sensitive")
    solvent = f_num(b, "solvent_content_pct", lo=0, hi=100)
    flash = f_num(b, "flash_point_c")
    pot_life = f_int(b, "pot_life_minutes", lo=0)
    shelf_life = f_int(b, "shelf_life_months", lo=0)
    spec_min = f_num(b, "spec_min_bond_strength_mpa", lo=0)
    min_shelf = f_int(b, "min_remaining_shelf_life_days", lo=0)
    if any(f["code"] == code for f in store.formulations.values()):
        raise ApiError(ERR_INVALID_REQUEST, "code must be unique across all formulations", 400)
    f = new_entity()
    f.update({
        "code": code,
        "name": name,
        "chemistry_family": family,
        "moisture_sensitive": moisture,
        "solvent_content_pct": solvent,
        "flash_point_c": flash,
        "pot_life_minutes": pot_life,
        "shelf_life_months": shelf_life,
        "spec_min_bond_strength_mpa": spec_min,
        "min_remaining_shelf_life_days": min_shelf,
        "status": "DRAFT",
    })
    store.formulations[f["id"]] = f
    return ok(ser_formulation(f), 201)


@bp.get("/api/formulations")
@require_roles(*ALL_ROLES)
def list_formulations():
    limit, offset = pagination_params()
    rows = [ser_formulation(f) for f in sorted_rows(store.formulations.values())]
    return ok_list(rows, limit, offset)


@bp.get("/api/formulations/<fid>")
@require_roles(*ALL_ROLES)
def get_one_formulation(fid):
    return ok(ser_formulation(get_formulation(fid)), 200)


@bp.post("/api/formulations/<fid>/activate")
@require_roles("PlantManager")
def activate_formulation(fid):
    f = get_formulation(fid)
    if f["status"] != "DRAFT":
        raise ApiError(ERR_FORMULATION_INVALID_STATE, "activate requires DRAFT", 409)
    f["status"] = "EFFECTIVE"
    touch(f)
    return ok(ser_formulation(f), 200)


@bp.post("/api/formulations/<fid>/withdraw")
@require_roles("PlantManager")
def withdraw_formulation(fid):
    f = get_formulation(fid)
    if f["status"] != "EFFECTIVE":
        raise ApiError(ERR_FORMULATION_INVALID_STATE, "withdraw requires EFFECTIVE", 409)
    if any(b["formulation_id"] == fid and b["status"] in BATCH_INFLIGHT
           for b in store.batches.values()):
        raise ApiError(
            ERR_FORMULATION_HAS_INFLIGHT_BATCHES,
            "Formulation has batches in MIXING, MIXED, or PACKING",
            409,
        )
    f["status"] = "WITHDRAWN"
    touch(f)
    return ok(ser_formulation(f), 200)


# ---------------------------------------------------------------------------
# MixingVessel
# ---------------------------------------------------------------------------

@bp.post("/api/mixing-vessels")
@require_roles("PlantManager")
def create_vessel():
    b = body_json()
    code = f_str(b, "vessel_code")
    cap = f_int(b, "capacity_liters", lo=1)
    if any(v["vessel_code"] == code for v in store.vessels.values()):
        raise ApiError(ERR_INVALID_REQUEST, "vessel_code must be unique", 400)
    v = new_entity()
    v.update({"vessel_code": code, "capacity_liters": cap})
    store.vessels[v["id"]] = v
    return ok(ser_vessel(v), 201)


@bp.get("/api/mixing-vessels/<vid>")
@require_roles(*ALL_ROLES)
def get_one_vessel(vid):
    return ok(ser_vessel(get_vessel(vid)), 200)


# ---------------------------------------------------------------------------
# DryRoom
# ---------------------------------------------------------------------------

@bp.post("/api/dry-rooms")
@require_roles("PlantManager")
def create_dry_room():
    b = body_json()
    code = f_str(b, "room_code")
    max_runs = f_int(b, "max_concurrent_runs", lo=1)
    humidity = f_num(b, "humidity_limit_pct")
    if any(d["room_code"] == code for d in store.dry_rooms.values()):
        raise ApiError(ERR_INVALID_REQUEST, "room_code must be unique", 400)
    d = new_entity()
    d.update({
        "room_code": code,
        "max_concurrent_runs": max_runs,
        "humidity_limit_pct": humidity,
    })
    store.dry_rooms[d["id"]] = d
    return ok(ser_dry_room(d), 201)


@bp.get("/api/dry-rooms/<did>")
@require_roles(*ALL_ROLES)
def get_one_dry_room(did):
    return ok(ser_dry_room(get_dry_room(did)), 200)
