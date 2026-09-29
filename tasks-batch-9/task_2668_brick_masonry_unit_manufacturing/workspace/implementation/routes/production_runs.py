"""Extrusion / setting runs: creation with clay commitment, and green close-out."""

from decimal import Decimal

import calc
import response
import services as svc
from auth import ALL_ROLES, actor, endpoint, is_plant_operator, require_plant_scope
from errors import ApiError
from routes import apply_filters
from store import db, new_row, touch
from validation import TEXTURES, body, raw_id, v_enum, v_id, v_int, v_str

from flask import Blueprint

bp = Blueprint("production_runs", __name__)

D = Decimal


@bp.get("/production-runs/<rid>")
@endpoint(ALL_ROLES)
def get_run(rid):
    return response.entity(svc.run_or_404(rid))


@bp.get("/production-runs")
@endpoint(ALL_ROLES)
def list_runs():
    rows = apply_filters(
        db.production_runs.values(),
        {
            "plant_id": "plant_id",
            "formulation_id": "formulation_id",
            "kiln_car_id": "kiln_car_id",
            "kiln_run_id": "kiln_run_id",
            "status": "status",
        },
    )
    return response.collection(rows)


# --------------------------------------------------------------------------
# POST /production-runs
# --------------------------------------------------------------------------
@bp.post("/production-runs")
@endpoint(["PlantOperator"])
def create_run():
    payload = body()

    # Ladder rule 5 — plant scoping, before payload well-formedness. The scope is
    # skipped for a body reference that does not resolve to a live row.
    require_plant_scope(raw_id(payload, "plant_id"))
    car_hint = db.kiln_cars.get(raw_id(payload, "kiln_car_id"))
    if car_hint is not None:
        require_plant_scope(car_hint["plant_id"])

    plant_id = v_id(payload, "plant_id")
    formulation_id = v_id(payload, "formulation_id")
    kiln_car_id = v_id(payload, "kiln_car_id")
    run_code = v_str(payload, "run_code")
    texture = v_enum(payload, "texture", TEXTURES)
    green_units_set = v_int(payload, "green_units_set", minv=1)

    plant = svc.plant_or_404(plant_id)
    formulation = svc.formulation_or_404(formulation_id)
    car = svc.car_or_404(kiln_car_id)

    svc.require_plant_active(plant)
    if car["status"] != "IDLE" or car.get("current_production_run_id") is not None:
        raise ApiError("ERR_KILN_CAR_NOT_IDLE", "The kiln car is not IDLE.")
    if formulation["status"] != "QUALIFIED":
        raise ApiError(
            "ERR_FORMULATION_NOT_QUALIFIED", "The body formulation is not QUALIFIED."
        )
    svc.require_unique(db.production_runs, "run_code", run_code)
    if green_units_set > int(car["capacity_green_units"]):
        raise ApiError(
            "ERR_KILN_CAR_CAPACITY_EXCEEDED",
            "green_units_set exceeds the kiln car's capacity.",
        )

    total_tons, amounts = svc.clay_split_for(formulation, green_units_set)
    svc.clay_commit(amounts)

    row = new_row(
        plant_id=plant_id,
        formulation_id=formulation_id,
        kiln_car_id=kiln_car_id,
        kiln_run_id=None,
        run_code=run_code,
        texture=texture,
        green_units_set=green_units_set,
        kiln_position=None,
        projected_net_green_units=calc.projected_net_green_units(green_units_set),
        green_loss_units=None,
        net_green_units=None,
        green_loss_pct=None,
        green_loss_variance_units=None,
        clay_tons_committed=total_tons,
        scrap_units=0,
        status="SETTING",
    )
    row["_pit_amounts"] = [[pit_id, tons] for pit_id, tons in amounts]
    db.production_runs[row["id"]] = row

    car["status"] = "SET"
    car["current_production_run_id"] = row["id"]
    touch(car)
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /production-runs/{id}/close-green
# --------------------------------------------------------------------------
@bp.post("/production-runs/<rid>/close-green")
@endpoint(["PlantOperator"])
def close_green(rid):
    run = svc.run_or_404(rid)
    require_plant_scope(run["plant_id"])
    payload = body()
    green_loss_units = v_int(
        payload, "green_loss_units", minv=0, maxv=int(run["green_units_set"])
    )

    svc.require_plant_active(db.plants.get(run["plant_id"]))
    if run["status"] != "SETTING":
        raise ApiError(
            "ERR_PRODUCTION_RUN_STATE_INVALID", "The production run is not SETTING."
        )

    green_units_set = int(run["green_units_set"])
    net = green_units_set - green_loss_units
    loss_pct = calc.green_loss_pct(green_loss_units, green_units_set)

    run["green_loss_units"] = green_loss_units
    run["net_green_units"] = net
    run["green_loss_pct"] = loss_pct
    run["green_loss_variance_units"] = net - int(run["projected_net_green_units"])
    run["status"] = "SET" if loss_pct <= calc.GREEN_LOSS_HOLD_PCT else "HELD"

    svc.clay_consume(svc.run_amounts(run))
    touch(run)
    return response.entity(run)
