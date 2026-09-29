"""Budget scenarios: creation, the waterfall run and adoption (PRD 3.4)."""
from flask import Blueprint, g

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive, waterfall

bp = Blueprint("scenarios", __name__)

READ_ROLES = ("BudgetOfficer", "PavementEngineer", "Inspector")


def _find_scenario(scenario_id):
    scenario = db.scenarios.get(scenario_id)
    if scenario is None:
        raise ApiError("ERR_SCENARIO_NOT_FOUND")
    return scenario


@bp.post("/budget-scenarios")
@endpoint("BudgetOfficer", "PavementEngineer")
def create_scenario():
    data = v.body()
    survey_id = v.field_id(data, "survey_id")
    scenario_name = v.field_string(data, "scenario_name", 1, 80)
    funding_cents = v.field_int(data, "funding_cents", minimum=0)
    strategy = v.field_enum(data, "strategy", waterfall.STRATEGIES)
    horizon_years = v.field_int(data, "horizon_years", minimum=1, maximum=20)

    if survey_id not in db.surveys:
        raise ApiError("ERR_SURVEY_NOT_FOUND")

    scenario = {
        "id": db.new_id(),
        "survey_id": survey_id,
        "scenario_name": scenario_name,
        "funding_cents": funding_cents,
        "strategy": strategy,
        "horizon_years": horizon_years,
        "analysis_date": clock.now(),
        "scenario_status": "DRAFT",
        "allocation_count": 0,
        "funded_cost_cents": 0,
        "backlog_cents": 0,
        "committed_cents": 0,
        "uncommitted_cents": 0,
        "projected_network_pci": None,
        "do_nothing_network_pci": None,
        "adopted_by_user_id": None,
    }
    scenario.update(db.audit())
    db.scenarios[scenario["id"]] = scenario
    return response.object_response(scenario, 201)


@bp.get("/budget-scenarios/<scenario_id>")
@endpoint(*READ_ROLES)
def read_scenario(scenario_id):
    return response.object_response(_find_scenario(scenario_id))


@bp.get("/budget-scenarios")
@endpoint(*READ_ROLES)
def list_scenarios():
    rows = v.filter_rows(db.ordered(db.scenarios.values()), {
        "survey_id": "survey_id",
        "scenario_status": "scenario_status",
        "strategy": "strategy",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/budget-scenarios/<scenario_id>/run")
@endpoint("PavementEngineer", "BudgetOfficer")
def run_scenario(scenario_id):
    v.body()
    scenario = _find_scenario(scenario_id)
    if scenario["scenario_status"] not in ("DRAFT", "COMPUTED"):
        raise ApiError("ERR_SCENARIO_NOT_RUNNABLE")
    for project in derive.projects_of_scenario(scenario["id"]):
        if project["delivery_status"] != "DRAFT":
            raise ApiError("ERR_SCENARIO_HAS_PROGRAMMED_PROJECTS")
    waterfall.run(scenario)
    return response.object_response(scenario)


@bp.post("/budget-scenarios/<scenario_id>/adopt")
@endpoint("BudgetOfficer")
def adopt_scenario(scenario_id):
    v.body()
    scenario = _find_scenario(scenario_id)
    if scenario["scenario_status"] != "COMPUTED":
        raise ApiError("ERR_SCENARIO_NOT_ADOPTABLE")
    if scenario["allocation_count"] < 1:
        raise ApiError("ERR_SCENARIO_HAS_NO_ALLOCATIONS")

    derive.apply_updates(scenario, {
        "scenario_status": "ADOPTED",
        "adopted_by_user_id": g.user_id,
    })
    derive.recompute_scenario_totals(scenario)
    for other in db.ordered(derive.scenarios_of_survey(scenario["survey_id"])):
        if other["id"] != scenario["id"] \
                and other["scenario_status"] == "ADOPTED":
            derive.apply_updates(other, {"scenario_status": "SUPERSEDED"})
    return response.object_response(scenario)
