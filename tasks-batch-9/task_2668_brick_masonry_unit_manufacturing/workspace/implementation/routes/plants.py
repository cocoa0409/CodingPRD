"""Plant registration, the idle cascade, and pit / kiln / car commissioning."""

from decimal import Decimal

import calc
import response
import services as svc
from auth import ALL_ROLES, endpoint, require_plant_scope
from routes import apply_filters
from store import db, new_row
from validation import (
    MATERIAL_TYPES,
    UNLOADING_EQUIPMENT,
    body,
    v_enum,
    v_enum_array,
    v_int,
    v_num,
    v_str,
)

from flask import Blueprint

bp = Blueprint("plants", __name__)

D = Decimal


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@bp.get("/plants/<pid>")
@endpoint(ALL_ROLES)
def get_plant(pid):
    return response.entity(svc.plant_or_404(pid))


@bp.get("/plants")
@endpoint(ALL_ROLES)
def list_plants():
    rows = apply_filters(db.plants.values(), {"status": "status"})
    return response.collection(rows)


@bp.get("/plants/<pid>/clay-pits")
@endpoint(ALL_ROLES)
def list_pits(pid):
    svc.plant_or_404(pid)
    rows = apply_filters(
        svc.pits_of_plant(pid), {"status": "status", "material_type": "material_type"}
    )
    return response.collection(rows)


@bp.get("/plants/<pid>/kilns")
@endpoint(ALL_ROLES)
def list_kilns(pid):
    svc.plant_or_404(pid)
    return response.collection(apply_filters(svc.kilns_of_plant(pid), {"status": "status"}))


@bp.get("/plants/<pid>/kiln-cars")
@endpoint(ALL_ROLES)
def list_cars(pid):
    svc.plant_or_404(pid)
    return response.collection(apply_filters(svc.cars_of_plant(pid), {"status": "status"}))


# --------------------------------------------------------------------------
# POST /plants
# --------------------------------------------------------------------------
@bp.post("/plants")
@endpoint(["PlantAdmin"])
def create_plant():
    payload = body()
    plant_code = v_str(payload, "plant_code", min_len=1, max_len=32)
    name = v_str(payload, "name")
    grid_x = v_int(payload, "grid_x", minv=-5000, maxv=5000)
    grid_y = v_int(payload, "grid_y", minv=-5000, maxv=5000)
    radius = v_int(payload, "market_radius_miles", minv=1)
    rate = v_int(payload, "freight_rate_cents_per_ton_mile", minv=1)
    capacity = v_int(payload, "base_capacity_green_units_per_day", minv=1)
    equipment = v_enum_array(payload, "unloading_equipment_available", UNLOADING_EQUIPMENT)

    svc.require_unique(db.plants, "plant_code", plant_code)

    row = new_row(
        plant_code=plant_code,
        name=name,
        grid_x=grid_x,
        grid_y=grid_y,
        market_radius_miles=radius,
        freight_rate_cents_per_ton_mile=rate,
        base_capacity_green_units_per_day=capacity,
        unloading_equipment_available=equipment,
        status="ACTIVE",
        fired_scrap_units=0,
        idled_at=None,
    )
    db.plants[row["id"]] = row
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /plants/{id}/idle
# --------------------------------------------------------------------------
@bp.post("/plants/<pid>/idle")
@endpoint(["PlantAdmin"])
def idle_plant(pid):
    plant = svc.plant_or_404(pid)
    svc.require_plant_active(plant)
    svc.idle_plant_cascade(plant)
    return response.entity(plant)


# --------------------------------------------------------------------------
# POST /plants/{id}/clay-pits
# --------------------------------------------------------------------------
@bp.post("/plants/<pid>/clay-pits")
@endpoint(["PlantAdmin"])
def open_pit(pid):
    plant = svc.plant_or_404(pid)
    payload = body()
    pit_name = v_str(payload, "pit_name")
    material_type = v_enum(payload, "material_type", MATERIAL_TYPES)
    reserve = v_num(payload, "proven_reserve_tons", 2, minv="0.01")
    iron = v_num(payload, "iron_oxide_pct", 3, minv="0.000", maxv="20.000")
    lime = v_num(payload, "lime_pct", 3, minv="0.000", maxv="10.000")

    svc.require_plant_active(plant)
    svc.require_unique(db.clay_pits, "pit_name", pit_name, "plant_id", pid)

    reserve = calc.rh(reserve, 2)
    row = new_row(
        plant_id=pid,
        pit_name=pit_name,
        material_type=material_type,
        proven_reserve_tons=reserve,
        iron_oxide_pct=iron,
        lime_pct=lime,
        available_tons=reserve,
        committed_tons=D("0.00"),
        consumed_tons=D("0.00"),
        status="OPEN",
    )
    db.clay_pits[row["id"]] = row
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /plants/{id}/kilns
# --------------------------------------------------------------------------
@bp.post("/plants/<pid>/kilns")
@endpoint(["PlantAdmin"])
def commission_kiln(pid):
    plant = svc.plant_or_404(pid)
    payload = body()
    kiln_code = v_str(payload, "kiln_code")
    position_count = v_int(payload, "position_count", minv=1, maxv=15)
    setpoint = v_int(payload, "setpoint_peak_c", minv=800, maxv=1300)
    cooldown = v_num(payload, "cooldown_buffer_hours", 1, minv="0.0")

    svc.require_plant_active(plant)
    svc.require_unique(db.kilns, "kiln_code", kiln_code, "plant_id", pid)

    row = new_row(
        plant_id=pid,
        kiln_code=kiln_code,
        position_count=position_count,
        setpoint_peak_c=setpoint,
        cooldown_buffer_hours=cooldown,
        status="AVAILABLE",
    )
    db.kilns[row["id"]] = row
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /plants/{id}/kiln-cars
# --------------------------------------------------------------------------
@bp.post("/plants/<pid>/kiln-cars")
@endpoint(["PlantAdmin", "PlantOperator"])
def register_car(pid):
    plant = svc.plant_or_404(pid)
    require_plant_scope(pid)
    payload = body()
    car_code = v_str(payload, "car_code")
    capacity = v_int(payload, "capacity_green_units", minv=1)

    svc.require_plant_active(plant)
    svc.require_unique(db.kiln_cars, "car_code", car_code, "plant_id", pid)

    row = new_row(
        plant_id=pid,
        car_code=car_code,
        capacity_green_units=capacity,
        status="IDLE",
        current_production_run_id=None,
    )
    db.kiln_cars[row["id"]] = row
    return response.entity_created(row)
