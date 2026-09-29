"""Business plan and stress scenario writes."""
from flask import Blueprint

import calc
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate, require_organizer_identity
from routes.helpers import must_get

bp = Blueprint("plans", __name__)

SCENARIO_CODES = ("BASELINE", "ADVERSE", "SEVERELY_ADVERSE")
YEARS = (1, 2, 3)


def _read_projections(data):
    values = {}
    for year in YEARS:
        values["projected_assets_y%d_cents" % year] = v.req_int(
            data, "projected_assets_y%d_cents" % year, 1, None)
    for family in ("loans", "deposits", "net_income"):
        for year in YEARS:
            key = "projected_%s_y%d_cents" % (family, year)
            if family == "net_income":
                values[key] = v.req_int(data, key)
            else:
                values[key] = v.req_int(data, key, 0, None)
    return values


@bp.post("/de-novo/business-plans")
def create_plan():
    authenticate(("CharterCounsel",))
    data = v.body()
    group_id = v.req_id(data, "group_id")
    expected_group_version = v.req_int(data, "expected_group_version", 0, None)
    supersedes_plan_id = v.opt_id(data, "supersedes_plan_id")
    opening_capital = v.req_int(data, "opening_tier1_capital_cents", 0, None)
    projections = _read_projections(data)
    branch_count = v.req_int(data, "projected_branch_count", 1, None)

    group = must_get("groups", group_id)
    superseded = None
    if supersedes_plan_id is not None:
        superseded = must_get("plans", supersedes_plan_id)

    if expected_group_version != group["version"]:
        raise err("ERR_STALE_GROUP_VERSION")
    if group["stage"] in ("OPEN", "ABANDONED"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    if superseded is not None:
        if superseded["group_id"] != group["id"] or superseded["status"] != "DRAFT":
            raise err("ERR_SUPERSEDE_TARGET_NOT_ELIGIBLE")
    for family in ("assets", "deposits"):
        first = projections["projected_%s_y1_cents" % family]
        second = projections["projected_%s_y2_cents" % family]
        third = projections["projected_%s_y3_cents" % family]
        if first > second or second > third:
            raise err("ERR_PROJECTION_NOT_MONOTONIC")
    for year in YEARS:
        if (projections["projected_loans_y%d_cents" % year]
                > projections["projected_assets_y%d_cents" % year]):
            raise err("ERR_LOANS_EXCEED_ASSETS")
    if opening_capital < calc.MIN_OPENING_CAPITAL_CENTS:
        raise err("ERR_OPENING_CAPITAL_BELOW_MINIMUM")

    row = {
        "group_id": group["id"],
        "supersedes_plan_id": supersedes_plan_id,
        "plan_revision_index": 1 if superseded is None else superseded["plan_revision_index"] + 1,
        "status": "DRAFT",
        "opening_tier1_capital_cents": opening_capital,
        "projected_branch_count": branch_count,
        "stress_scenario_count": 0,
        "breach_scenario_count": 0,
        "worst_governing_min_leverage_ratio_bps": 0,
    }
    row.update(projections)
    plan = db.insert("plans", row)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
    db.touch(group)
    db.commit()
    return response.object_response(serialize.plan(plan), 201)


@bp.post("/de-novo/business-plans/<plan_id>/stress-scenarios")
def create_scenario(plan_id):
    authenticate(("CharterCounsel",))
    data = v.body()
    scenario_code = v.req_enum(data, "scenario_code", SCENARIO_CODES)
    credit_loss_rate_bps = v.req_int(data, "credit_loss_rate_bps", 0, 5000)
    nim_compression_bps = v.req_int(data, "nim_compression_bps", 0, 2000)
    expense_overrun_cents = v.req_int(data, "expense_overrun_cents", 0, None)
    plan = must_get("plans", plan_id)
    if plan["status"] != "DRAFT":
        raise err("ERR_PLAN_NOT_EDITABLE")
    for row in calc.scenarios_of(plan["id"]):
        if row["scenario_code"] == scenario_code:
            raise err("ERR_SCENARIO_CODE_DUPLICATE")
    scenario = db.insert("scenarios", {
        "business_plan_id": plan["id"],
        "scenario_code": scenario_code,
        "credit_loss_rate_bps": credit_loss_rate_bps,
        "nim_compression_bps": nim_compression_bps,
        "expense_overrun_cents": expense_overrun_cents,
        "static_min_leverage_ratio_bps": 0,
        "static_breach_year_index": 0,
        "dynamic_min_leverage_ratio_bps": 0,
        "dynamic_breach_year_index": 0,
        "governing_variant": None,
        "governing_min_leverage_ratio_bps": 0,
        "governing_breach_year_index": 0,
    })
    calc.recompute_scenario(plan, scenario)
    calc.recompute_plan_aggregates(plan)
    db.touch(plan)
    db.commit()
    return response.object_response(serialize.scenario(scenario), 201)


@bp.post("/de-novo/business-plans/<plan_id>/submit")
def submit_plan(plan_id):
    authenticate(("LeadOrganizer",))
    v.body()
    plan = must_get("plans", plan_id)
    group = db.get("groups", plan["group_id"])
    require_organizer_identity(plan["group_id"])
    if plan["status"] != "DRAFT":
        raise err("ERR_PLAN_NOT_EDITABLE")
    if group is None or group["composition_status"] != "COMPOSITION_MET":
        raise err("ERR_GROUP_COMPOSITION_INCOMPLETE")
    if group["management_composite_score"] < calc.MIN_MANAGEMENT_COMPOSITE_SCORE:
        raise err("ERR_MANAGEMENT_SCORE_BELOW_MINIMUM")
    scenarios = calc.scenarios_of(plan["id"])
    if len(scenarios) < 1:
        raise err("ERR_STRESS_SCENARIO_REQUIRED")
    for scenario in scenarios:
        if scenario["governing_min_leverage_ratio_bps"] < calc.DE_NOVO_FLOOR_LEVERAGE_BPS:
            raise err("ERR_STRESS_CAPITAL_SHORTFALL")
    verdict = calc.capital_adequacy_verdict(group, plan)
    if verdict["verdict"] != "ADEQUATE":
        raise err("ERR_CAPITAL_INADEQUATE")
    plan["status"] = "SUBMITTED"
    db.touch(plan)
    db.commit()
    return response.object_response(serialize.plan(plan))
