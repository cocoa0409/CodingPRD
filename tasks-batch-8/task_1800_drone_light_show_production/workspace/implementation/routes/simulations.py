"""SimulationRun endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import serialize_simulation_run, serialize_design, touch

bp = Blueprint("simulations", __name__)


@bp.route("/api/simulation-runs", methods=["POST"])
def create_simulation_run():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_design_id", "min_separation_observed_m",
                        "battery_draw_pct", "max_speed_mps"])
    require_role("ProductionPlanner")
    design_id = body["show_design_id"]
    if not isinstance(design_id, str):
        raise errors.validation("show_design_id must be a string")
    min_sep = V.req_number(body, "min_separation_observed_m")
    draw = V.req_number(body, "battery_draw_pct")
    speed = V.req_number(body, "max_speed_mps")
    if min_sep < 0:
        raise errors.validation("min_separation_observed_m must be >= 0")
    if not (0 <= draw <= 100):
        raise errors.validation("battery_draw_pct must be within [0, 100]")
    if speed < 0:
        raise errors.validation("max_speed_mps must be >= 0")

    design = DB.designs.get(design_id)
    if design is None:
        raise errors.not_found("ERR_DESIGN_NOT_FOUND", "design not found")

    verdict = calc.simulation_verdict(design, min_sep, draw, speed)

    rid = new_id()
    ts = wall_created_at()
    run = {
        "id": rid, "show_design_id": design_id,
        "min_separation_observed_m": min_sep,
        "battery_draw_pct": draw, "max_speed_mps": speed,
        "verdict": verdict,
        "created_at": ts,
    }
    DB.simulation_runs[rid] = run
    DB.insertion_order["simulation_runs"].append(rid)

    # first run moves design DRAFT -> SIMULATED
    if design["status"] == "DRAFT":
        design["status"] = "SIMULATED"
        touch(design)

    return success_object(serialize_simulation_run(run), 201)


@bp.route("/api/simulation-runs/<simulationRunId>", methods=["GET"])
def get_simulation_run(simulationRunId):
    get_auth()
    run = DB.simulation_runs.get(simulationRunId)
    if run is None:
        raise errors.not_found("ERR_SIMULATION_RUN_NOT_FOUND", "simulation run not found")
    return success_object(serialize_simulation_run(run))


@bp.route("/api/simulation-runs", methods=["GET"])
def list_simulation_runs():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    design_id = V.opt_string(request.args, "show_design_id")
    verdict = V.opt_string(request.args, "verdict")
    items = [DB.simulation_runs[i] for i in DB.insertion_order["simulation_runs"]]
    if design_id is not None:
        items = [r for r in items if r["show_design_id"] == design_id]
    if verdict is not None:
        items = [r for r in items if r["verdict"] == verdict]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_simulation_run(r) for r in page], limit, offset, total)
