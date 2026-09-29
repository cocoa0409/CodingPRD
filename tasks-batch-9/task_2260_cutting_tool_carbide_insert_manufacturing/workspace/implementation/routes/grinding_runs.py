"""Grinding cells, runs and tolerance control (PRD section 3.4)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("grinding_runs", __name__)

READ_ROLES = ["ProductionPlanner", "QualityApprover", "GeometryEngineer", "ApplicationEngineer"]
OWNER = ["ProductionPlanner"]

BUFFER = timedelta(minutes=calc.CELL_SETUP_BUFFER_MIN)


def _cell_neighbours(cell_id):
    return [
        r
        for r in db.grinding_runs.values()
        if r["cell_id"] == cell_id and r["status"] in ("SCHEDULED", "COMPLETED")
    ]


@bp.route("/tooling/grinding-runs", methods=["POST"])
def create():
    authenticate(OWNER)
    payload = v.body(
        required=(
            "wheel_id",
            "product_id",
            "cell_id",
            "window_start",
            "window_end",
            "planned_units",
        )
    )
    wheel_id = v.as_id(payload, "wheel_id")
    product_id = v.as_id(payload, "product_id")
    cell_id = v.as_enum(payload, "cell_id", c.CELLS)
    start = v.as_datetime(payload, "window_start")
    end = v.as_datetime(payload, "window_end")
    planned = v.as_int(payload, "planned_units", minimum=1)

    wheel = derive.must_exist("wheels", wheel_id)
    product = derive.must_exist("products", product_id)

    if wheel["status"] == "EXPIRED":
        raise ApiError("ERR_WHEEL_EXPIRED", "An EXPIRED wheel cannot be mounted.")
    if wheel["status"] == "DRESSING":
        raise ApiError(
            "ERR_WHEEL_REQUIRES_DRESSING",
            "The wheel has fallen below its dressing threshold and must be dressed first.",
        )
    if not start < end:
        raise ApiError(
            "ERR_INVALID_WINDOW", "window_start must be strictly earlier than window_end."
        )
    if start < db.now_dt():
        raise ApiError("ERR_WINDOW_IN_PAST", "window_start lies before the current logical time.")

    neighbours = _cell_neighbours(cell_id)
    for run in neighbours:
        if start <= run["_we"] and run["_ws"] <= end:
            raise ApiError(
                "ERR_CELL_DOUBLE_BOOKED",
                "Cell %s is already occupied for part of that closed window." % cell_id,
            )
    for run in neighbours:
        if run["_we"] < start:
            gap = start - run["_we"]
        else:
            gap = run["_ws"] - end
        if gap < BUFFER:
            raise ApiError(
                "ERR_CELL_BUFFER_CONFLICT",
                "Cell %s needs a %d minute setup buffer between runs."
                % (cell_id, calc.CELL_SETUP_BUFFER_MIN),
            )

    row = db.new_row(
        {
            "wheel_id": wheel["id"],
            "product_id": product["id"],
            "cell_id": cell_id,
            "window_start": payload["window_start"],
            "window_end": payload["window_end"],
            "planned_units": planned,
            "produced_units": 0,
            "scrap_units": 0,
            "measured_diameter_dev_um": None,
            "tolerance_class": None,
            "consumed_life_units": 0,
            "status": "SCHEDULED",
            "_ws": start,
            "_we": end,
        }
    )
    db.grinding_runs[row["id"]] = row
    return object_response(serialize.grinding_run(row), 201)


@bp.route("/tooling/grinding-runs", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "grinding_runs",
        READ_ROLES,
        {
            "wheel_id": None,
            "product_id": None,
            "cell_id": c.CELLS,
            "status": c.GRINDING_RUN_STATUSES,
        },
    )
    return c.list_response("grinding_runs", rows, limit, offset)


@bp.route("/tooling/grinding-runs/<run_id>", methods=["GET"])
def read(run_id):
    return c.read_one("grinding_runs", run_id, READ_ROLES)


@bp.route("/tooling/grinding-runs/<run_id>/complete", methods=["POST"])
def complete(run_id):
    authenticate(OWNER)
    payload = v.body(required=("produced_units", "scrap_units", "measured_diameter_dev_um"))
    produced = v.as_int(payload, "produced_units", minimum=0)
    scrap = v.as_int(payload, "scrap_units", minimum=0)
    deviation = v.as_number(payload, "measured_diameter_dev_um")

    run = derive.must_exist("grinding_runs", run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_GRINDING_RUN_STATE",
            "Only a SCHEDULED run may be completed (currently %s)." % run["status"],
        )
    if db.now_dt() < run["_we"]:
        raise ApiError(
            "ERR_WINDOW_NOT_ELAPSED",
            "The run's window has not elapsed on the logical clock yet.",
        )
    if produced + scrap != run["planned_units"]:
        raise ApiError(
            "ERR_UNIT_COUNT_MISMATCH",
            "produced_units + scrap_units must equal planned_units (%d)." % run["planned_units"],
        )

    product = db.products.get(run["product_id"])
    charge = (produced + scrap) * (product["grind_units_per_tool"] if product else 0)

    run["produced_units"] = produced
    run["scrap_units"] = scrap
    run["measured_diameter_dev_um"] = deviation
    run["tolerance_class"] = calc.grinding_tolerance_class(deviation)
    run["consumed_life_units"] = charge
    run["status"] = "COMPLETED"
    db.touch(run)

    wheel = db.wheels.get(run["wheel_id"])
    if wheel is not None:
        derive.wheel_charge(wheel, charge)
    return object_response(serialize.grinding_run(run))


@bp.route("/tooling/grinding-runs/<run_id>/void", methods=["POST"])
def void(run_id):
    authenticate(["ProductionPlanner", "QualityApprover"])
    payload = v.body(required=("void_reason",))
    v.as_string(payload, "void_reason")

    run = derive.must_exist("grinding_runs", run_id)
    if run["status"] not in ("SCHEDULED", "COMPLETED"):
        raise ApiError(
            "ERR_INVALID_GRINDING_RUN_STATE",
            "Only a SCHEDULED or COMPLETED run may be voided (currently %s)." % run["status"],
        )

    was_completed = run["status"] == "COMPLETED"
    charge = run["consumed_life_units"]
    run["status"] = "VOIDED"
    if was_completed:
        run["consumed_life_units"] = 0
        run["produced_units"] = 0
        run["scrap_units"] = 0
        run["measured_diameter_dev_um"] = None
        run["tolerance_class"] = None
    db.touch(run)

    if was_completed:
        wheel = db.wheels.get(run["wheel_id"])
        if wheel is not None:
            derive.wheel_reverse(wheel, charge)
    return object_response(serialize.grinding_run(run))
