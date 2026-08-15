"""StressScenario endpoints."""

from __future__ import annotations

from flask import Blueprint

from db import stress_scenarios, capital_plans, stamp_new, touch
from errors import (
    raise_err, ERR_INVARIANT_VIOLATION, ERR_SCENARIO_LIMIT, ERR_SCENARIO_IN_USE,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_scenario, get_bank, get_scenario, compute_projected_pre_tax_loss,
    MAX_ACTIVE_SCENARIOS, IN_FLIGHT_PLAN_STATES,
)
from util import get_body, req_str, req_int, apply_filters, sorted_page

bp = Blueprint("scenarios", __name__)


@bp.route("/banks/<bankId>/stress-scenarios", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_scenario(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    code = req_str(body, "scenario_code")
    gdp = req_int(body, "gdp_shock_bps")
    unemp = req_int(body, "unemployment_peak_bps")
    hpi = req_int(body, "hpi_shock_bps")
    cre = req_int(body, "cre_price_shock_bps")
    market = req_int(body, "market_shock_bps")
    # Uniqueness invariant: scenario_code unique among non-RETIRED (priority 8).
    for s in stress_scenarios.values():
        if (s["bank_id"] == bank["id"] and s["scenario_code"] == code
                and s["status"] != "RETIRED"):
            raise_err(ERR_INVARIANT_VIOLATION,
                      "scenario_code must be unique among non-RETIRED scenarios")
    scenario = {
        "bank_id": bank["id"],
        "scenario_code": code,
        "gdp_shock_bps": gdp,
        "unemployment_peak_bps": unemp,
        "hpi_shock_bps": hpi,
        "cre_price_shock_bps": cre,
        "market_shock_bps": market,
        "projected_pre_tax_loss_cents": None,
        "status": "DRAFT",
    }
    stamp_new(scenario)
    stress_scenarios[scenario["id"]] = scenario
    return success_object(ser_scenario(scenario), 201)


@bp.route("/banks/<bankId>/stress-scenarios/<scenarioId>", methods=["GET"])
@require_roles("Any")
def get_one_scenario(bankId: str, scenarioId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_scenario(get_scenario(bank, scenarioId)))


@bp.route("/banks/<bankId>/stress-scenarios", methods=["GET"])
@require_roles("Any")
def list_scenarios(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [s for s in stress_scenarios.values() if s["bank_id"] == bank["id"]]
    items = apply_filters(items, {"status": "status"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_scenario(s) for s in page], limit, offset, total)


@bp.route("/banks/<bankId>/stress-scenarios/<scenarioId>/activate", methods=["POST"])
@require_roles("CapitalAnalyst")
def activate_scenario(bankId: str, scenarioId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    scenario = get_scenario(bank, scenarioId)
    if scenario["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT scenario can be activated")
    active_count = sum(
        1 for s in stress_scenarios.values()
        if s["bank_id"] == bank["id"] and s["status"] == "ACTIVE"
    )
    if active_count >= MAX_ACTIVE_SCENARIOS:
        raise_err(ERR_SCENARIO_LIMIT,
                  "Bank already has MAX_ACTIVE_SCENARIOS (=2) scenarios ACTIVE")
    scenario["projected_pre_tax_loss_cents"] = compute_projected_pre_tax_loss(bank, scenario)
    scenario["status"] = "ACTIVE"
    touch(scenario)
    return success_object(ser_scenario(scenario))


@bp.route("/banks/<bankId>/stress-scenarios/<scenarioId>/retire", methods=["POST"])
@require_roles("CapitalAnalyst")
def retire_scenario(bankId: str, scenarioId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    scenario = get_scenario(bank, scenarioId)
    if scenario["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE scenario can be retired")
    for plan in capital_plans.values():
        if (plan["bank_id"] == bank["id"] and plan.get("stress_scenario_id") == scenario["id"]
                and plan["status"] in IN_FLIGHT_PLAN_STATES):
            raise_err(ERR_SCENARIO_IN_USE,
                      "Scenario is referenced by an in-flight CapitalPlan")
    scenario["status"] = "RETIRED"
    touch(scenario)
    return success_object(ser_scenario(scenario))
