"""Water supply evaluations: the projected curve and the margin verdict (PRD 3.4)."""
from flask import Blueprint

import calc_supply
import cascades
import clock
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from utils import days, parse_dt

bp = Blueprint("evaluations", __name__)


@bp.post("/water-supply-evaluations")
def create_evaluation():
    actor = authenticate(["DesignEngineer"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    flow_test = guards.must_fk("flow_test", validate.raw_fk(data, "flow_test_id"))
    calc = guards.must_fk(
        "calculation", validate.raw_fk(data, "governing_hydraulic_calculation_id")
    )
    guards.require_lead_engineer(actor, project)
    row = {
        "project_id": validate.req_str(data, "project_id"),
        "flow_test_id": validate.req_str(data, "flow_test_id"),
        "governing_hydraulic_calculation_id": validate.req_str(
            data, "governing_hydraulic_calculation_id"
        ),
        "evaluation_basis": validate.req_str(
            data, "evaluation_basis", enum=calc_supply.EVALUATION_BASES
        ),
    }
    guards.require_not_frozen(project)

    # step 22: the referenced flow test must still be within its validity window
    tested_at = parse_dt(flow_test["tested_at"])
    if tested_at < clock.now() - days(calc_supply.FLOW_TEST_VALIDITY_DAYS):
        raise ApiError(
            "ERR_FLOW_TEST_STALE",
            "The referenced flow test is older than the 365 day validity window.",
        )
    # step 35: the referenced calculation must have an active chain
    if (calc.get("iteration_count") or 0) < 1:
        raise ApiError(
            "ERR_NO_ITERATIONS_IN_CHAIN",
            "The referenced calculation has no iteration in its active chain.",
        )

    cascades.supersede_current_evaluations(project)
    row.update(calc_supply.evaluate(flow_test, calc, project, row["evaluation_basis"]))
    row["pinned_calculation_iteration_count"] = calc["iteration_count"]
    row["pump_sized"] = False
    row["state"] = "EVALUATED"
    db.stamp_create(row)
    db.evaluations[row["id"]] = row

    project["pump_required_flag"] = row["margin_verdict"] != "ADEQUATE"
    ledger.recompute_posture(project)
    db.touch(project)
    return response.created(response.public(row))


@bp.get("/water-supply-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("evaluation", evaluation_id)))


@bp.get("/water-supply-evaluations")
def list_evaluations():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.evaluations.values()),
        [
            "project_id",
            "flow_test_id",
            "governing_hydraulic_calculation_id",
            "state",
            "margin_verdict",
        ],
    )
    return helpers.list_response(rows)
