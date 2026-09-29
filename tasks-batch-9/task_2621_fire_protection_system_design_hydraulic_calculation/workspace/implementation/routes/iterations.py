"""The append-only pipe-sizing chain (PRD 3.3)."""
from flask import Blueprint

import calc_chain
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from routes.calculations import newest_evaluated_evaluation
from utils import _dec, rhu

bp = Blueprint("iterations", __name__)

APPENDABLE_STATES = ("DRAFT", "ITERATING", "PRESSURE_DEFICIENT", "REOPENED")
RESTART_REQUIRED_STATES = ("PRESSURE_DEFICIENT", "REOPENED")
RESTART_FORBIDDEN_STATES = ("DRAFT", "ITERATING")


@bp.post("/hydraulic-calculations/<calc_id>/iterations")
def append_iteration(calc_id):
    actor = authenticate(["DesignEngineer"])
    calc = guards.must("calculation", calc_id)
    project = guards.must("project", calc["project_id"])
    guards.require_lead_engineer(actor, project)

    data = validate.body()
    row = {
        "hydraulic_calculation_id": calc["id"],
        "iteration_index": validate.req_int(data, "iteration_index", ge=1),
        "pipe_size_in": validate.req_str(data, "pipe_size_in", enum=calc_chain.PIPE_SIZES),
        "length_ft": validate.req_num(data, "length_ft", gt=0),
        "fitting_equivalent_ft": validate.req_num(data, "fitting_equivalent_ft", ge=0),
        "flow_gpm": validate.req_num(data, "flow_gpm", gt=0),
        "elevation_change_ft": validate.req_num(data, "elevation_change_ft"),
        "is_supply_connection": validate.opt_bool(data, "is_supply_connection", default=False),
        "restart_chain": validate.opt_bool(data, "restart_chain", default=False),
    }

    guards.require_not_frozen(project)
    if calc["state"] == "ARCHIVED":
        guards.terminal("The calculation is ARCHIVED; no further iteration may be appended.")
    if calc["state"] not in APPENDABLE_STATES:
        guards.invalid_transition(
            "No iteration append is declared for a calculation in state %s." % calc["state"]
        )
    evaluation = None
    if row["is_supply_connection"]:
        if calc["state"] != "ITERATING":
            guards.invalid_transition(
                "A supply-connection iteration is only declared from ITERATING."
            )
        evaluation = newest_evaluated_evaluation(project["id"])
        if evaluation is None:
            guards.invalid_transition(
                "No EVALUATED water supply evaluation exists for this project, so no convergence branch is declared."
            )

    # step 20: the velocity limit, inclusive at exactly 32.00 fps
    row["friction_loss_psi"] = calc_chain.friction_loss_psi(
        row["pipe_size_in"], row["flow_gpm"], row["length_ft"], row["fitting_equivalent_ft"]
    )
    row["elevation_loss_psi"] = calc_chain.elevation_loss_psi(row["elevation_change_ft"])
    row["velocity_fps"] = calc_chain.velocity_fps(row["pipe_size_in"], row["flow_gpm"])
    if _dec(row["velocity_fps"]) > _dec(calc_chain.VELOCITY_LIMIT_FPS):
        raise ApiError(
            "ERR_VELOCITY_LIMIT_EXCEEDED",
            "The segment's velocity exceeds the velocity limit of 32.00 feet per second.",
        )

    # step 24: the closing segment must carry the calculation's design flow
    if row["is_supply_connection"] and _dec(row["flow_gpm"]) != _dec(calc["design_flow_gpm"]):
        raise ApiError(
            "ERR_SUPPLY_FLOW_MISMATCH",
            "A supply-connection iteration must carry flow_gpm equal to design_flow_gpm.",
        )

    # step 33: sequence, counting rows already superseded out of the active chain
    existing = calc_chain.iterations_of(calc["id"])
    if row["iteration_index"] != len(existing) + 1:
        raise ApiError(
            "ERR_ITERATION_OUT_OF_SEQUENCE",
            "iteration_index must equal the calculation's current iteration row count plus one.",
        )

    # step 34: restart_chain must agree with the calculation's state
    if calc["state"] in RESTART_REQUIRED_STATES and not row["restart_chain"]:
        raise ApiError(
            "ERR_CHAIN_RESTART_REQUIRED",
            "restart_chain must be true while the calculation is in %s." % calc["state"],
        )
    if calc["state"] in RESTART_FORBIDDEN_STATES and row["restart_chain"]:
        raise ApiError(
            "ERR_CHAIN_RESTART_REQUIRED",
            "restart_chain must be false or absent while the calculation is in %s." % calc["state"],
        )

    row["cumulative_psi_after"] = 0.0
    row["in_active_chain"] = True
    db.stamp_create(row, common_fields=False)
    db.iterations[row["id"]] = row

    before_project = db.snapshot(project)
    previous_state = calc["state"]
    if row["restart_chain"]:
        calc["chain_start_index"] = row["iteration_index"]
    calc_chain.recompute_chain(calc)
    if previous_state == "DRAFT":
        calc["state"] = "ITERATING"
    elif previous_state in RESTART_REQUIRED_STATES:
        calc["state"] = "ITERATING"
        if previous_state == "REOPENED":
            calc["stale_reason"] = None

    if row["is_supply_connection"]:
        required = rhu(
            _dec(row["cumulative_psi_after"])
            + _dec(project["underground_lead_in_loss_psi"]),
            2,
        )
        available = _dec(evaluation["available_psi_at_demand"])
        if _dec(required) <= available:
            calc["state"] = "CONVERGED"
            calc["deficiency_psi"] = None
        else:
            calc["state"] = "PRESSURE_DEFICIENT"
            calc["deficiency_psi"] = rhu(_dec(required) - available, 2)
            project["pump_required_flag"] = True

    db.touch(calc)
    ledger.recompute_ledger(project)
    ledger.recompute_posture(project)
    db.touch_if_changed(project, before_project)
    return response.created(response.public(row))


@bp.get("/hydraulic-calculations/<calc_id>/iterations")
def list_iterations(calc_id):
    authenticate(ALL_ROLES)
    guards.must("calculation", calc_id)
    rows = calc_chain.iterations_of(calc_id)
    rows = helpers.apply_bool_filter(rows, "in_active_chain")
    return helpers.list_response(rows, ordered=True)


@bp.get("/hydraulic-calculations/<calc_id>/submittals")
def list_calculation_submittals(calc_id):
    authenticate(ALL_ROLES)
    guards.must("calculation", calc_id)
    rows = [
        s
        for s in db.submittals.values()
        if calc_id in (s.get("included_calculation_ids") or [])
    ]
    rows = helpers.apply_filters(rows, ["state"])
    return helpers.list_response(rows)
