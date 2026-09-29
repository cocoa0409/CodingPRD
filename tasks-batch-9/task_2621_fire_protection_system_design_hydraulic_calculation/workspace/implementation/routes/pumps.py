"""Fire pump sizing against a deficient supply evaluation (PRD 3.4)."""
from flask import Blueprint

import calc_pump
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate

bp = Blueprint("pumps", __name__)


@bp.post("/fire-pumps")
def create_pump():
    actor = authenticate(["DesignEngineer"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    evaluation = guards.must_fk(
        "evaluation", validate.raw_fk(data, "water_supply_evaluation_id")
    )
    guards.require_lead_engineer(actor, project)
    row = {
        "project_id": validate.req_str(data, "project_id"),
        "water_supply_evaluation_id": validate.req_str(data, "water_supply_evaluation_id"),
        "model_tag": validate.opt_str(data, "model_tag", default="TBD"),
    }
    pinned = validate.req_int(data, "expected_water_supply_evaluation_version")

    # step 12: the evaluation version pin (PRD 2.7)
    if pinned != evaluation["version"]:
        raise ApiError(
            "ERR_STALE_SUPPLY_EVALUATION_VERSION",
            "expected_water_supply_evaluation_version does not match the evaluation's current version.",
        )
    guards.require_not_frozen(project)
    if evaluation["state"] != "EVALUATED" or evaluation["margin_verdict"] == "ADEQUATE":
        raise ApiError(
            "ERR_PUMP_NOT_REQUIRED",
            "The referenced evaluation is not an evaluated, deficient supply.",
        )
    if evaluation["pump_sized"]:
        raise ApiError(
            "ERR_PUMP_ALREADY_SIZED",
            "A pump has already been sized against this evaluation.",
        )

    row.update(calc_pump.size(evaluation))
    row["state"] = "SIZED"
    db.stamp_create(row)
    db.pumps[row["id"]] = row

    evaluation["pump_sized"] = True
    db.touch(evaluation)
    project["pump_required_flag"] = True
    ledger.recompute_posture(project)
    db.touch(project)
    return response.created(response.public(row))


@bp.get("/fire-pumps/<pump_id>")
def get_pump(pump_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("pump", pump_id)))


@bp.get("/fire-pumps")
def list_pumps():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.pumps.values()),
        ["project_id", "water_supply_evaluation_id", "state", "sizing_verdict"],
    )
    return helpers.list_response(rows)
