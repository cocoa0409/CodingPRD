"""Scenario allocations: the waterfall's rows plus manual adds (PRD 3.4)."""
from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive, waterfall

bp = Blueprint("allocations", __name__)

READ_ROLES = ("BudgetOfficer", "PavementEngineer", "Inspector")


@bp.post("/scenario-allocations")
@endpoint("BudgetOfficer")
def create_allocation():
    data = v.body()
    scenario_id = v.field_id(data, "scenario_id")
    candidate_id = v.field_id(data, "candidate_id")
    expected_version = v.field_int(data, "expected_scenario_version")

    scenario = db.scenarios.get(scenario_id)
    if scenario is None:
        raise ApiError("ERR_SCENARIO_NOT_FOUND")
    candidate = db.candidates.get(candidate_id)
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND")

    if expected_version != scenario["version"]:
        raise ApiError("ERR_STALE_SCENARIO_VERSION")
    if scenario["scenario_status"] not in ("DRAFT", "COMPUTED"):
        raise ApiError("ERR_SCENARIO_FROZEN")
    if candidate["survey_id"] != scenario["survey_id"]:
        raise ApiError("ERR_CANDIDATE_SURVEY_MISMATCH")
    if scenario["funded_cost_cents"] + candidate["estimated_cost_cents"] \
            > scenario["funding_cents"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_FUNDING")

    allocation = waterfall.new_allocation(
        scenario["id"], candidate["id"], waterfall.next_rank(scenario["id"]),
        "FUNDED", candidate["estimated_cost_cents"], "MANUAL_ADD",
    )
    derive.recompute_scenario_totals(scenario)
    return response.object_response(allocation, 201)


@bp.get("/scenario-allocations/<allocation_id>")
@endpoint(*READ_ROLES)
def read_allocation(allocation_id):
    allocation = db.allocations.get(allocation_id)
    if allocation is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    return response.object_response(allocation)


@bp.get("/scenario-allocations")
@endpoint(*READ_ROLES)
def list_allocations():
    rows = sorted(db.allocations.values(), key=lambda a: (a["rank"], a["_seq"]))
    rows = v.filter_rows(rows, {
        "scenario_id": "scenario_id",
        "candidate_id": "candidate_id",
        "allocation_status": "allocation_status",
        "source": "source",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)
