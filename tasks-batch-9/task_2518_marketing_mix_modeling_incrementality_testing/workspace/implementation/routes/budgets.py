"""Budget scenarios and allocation rows (PRD section 3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import db as store
from db import base_row, db
from errors import ApiError
from lookup import must, must_field
from middleware import ANALYTICS_LEAD, BRAND_PLANNER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.budget import (perform_approve, perform_optimize, perform_revert,
                             refresh_allocation_totals)
from services.window import PERIOD_DAYS
from validation import (date_style, field_date, field_decimal, field_int, get_body, invalid)

bp = Blueprint("budgets", __name__)

BINDINGS = ("NONE", "FLOOR", "CEILING")


@bp.post("/mmm/budget-scenarios")
def create_scenario():
    user_id = authenticate((BRAND_PLANNER,))
    body = get_body()
    total_budget_cents = field_int(body, "total_budget_cents", minimum=1)
    start_raw, start = field_date(body, "planning_start_date")
    end_raw, end = field_date(body, "planning_end_date")
    fee_pct = field_decimal(body, "reallocation_fee_pct", required=False,
                            default=Decimal("0.00"), minimum=0, maximum=5, max_places=2)
    if end <= start:
        raise invalid("planning_end_date must be strictly after planning_start_date.")

    market = must_field("markets", body, "market_id")
    run = must_field("model_runs", body, "model_run_id")

    if run["market_id"] != market["id"]:
        raise invalid("The model run does not belong to the referenced market.")

    window = db.data_windows.get(run["data_window_id"])
    period_days = PERIOD_DAYS[window["granularity"]]
    span_days = (end - start).days
    if span_days % period_days != 0:
        raise invalid("The planning horizon must divide evenly into the run's period length.")
    planning_period_count = span_days // period_days

    # PRD 2.12: the run-state check outranks the budget-ceiling check.
    if run["publication_status"] != "PUBLISHED" or run["fit_status"] != "FITTED":
        raise ApiError("ERR_MODEL_RUN_NOT_PUBLISHED",
                       "A budget scenario needs a PUBLISHED, FITTED model run.")
    if total_budget_cents > market["annual_budget_ceiling_cents"]:
        raise ApiError("ERR_BUDGET_CEILING_EXCEEDED",
                       "total_budget_cents exceeds the market's annual budget ceiling.")

    row = base_row("budget_scenarios")
    row.update({
        "market_id": market["id"],
        "model_run_id": run["id"],
        "total_budget_cents": total_budget_cents,
        "planning_start_date": start_raw,
        "planning_end_date": end_raw,
        "planning_period_count": planning_period_count,
        "reallocation_fee_pct": fee_pct,
        "reallocation_fee_cents": 0,
        "allocated_total_cents": 0,
        "unallocated_cents": 0,
        "shifted_total_cents": 0,
        "projected_contribution_units": Decimal("0.0000"),
        "projected_incremental_revenue_cents": 0,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "_planning_start_date": start,
        "_planning_end_date": end,
        "_date_style": date_style(start_raw),
    })
    db.add("budget_scenarios", row)
    return created(row)


@bp.get("/mmm/budget-scenarios")
def list_scenarios():
    authenticate(READ_ROLES)
    rows = db.all("budget_scenarios")
    for param in ("market_id", "model_run_id", "status"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(ordering.sort_rows("budget_scenarios", rows), request.args)


@bp.get("/mmm/budget-scenarios/<scenario_id>")
def get_scenario(scenario_id):
    authenticate(READ_ROLES)
    return ok(must("budget_scenarios", scenario_id))


@bp.post("/mmm/budget-scenarios/<scenario_id>/optimize")
def optimize_scenario(scenario_id):
    authenticate((BRAND_PLANNER,))
    scenario = must("budget_scenarios", scenario_id)
    return ok(perform_optimize(scenario))


@bp.post("/mmm/budget-scenarios/<scenario_id>/revert-optimization")
def revert_scenario(scenario_id):
    authenticate((BRAND_PLANNER,))
    scenario = must("budget_scenarios", scenario_id)
    return ok(perform_revert(scenario))


@bp.post("/mmm/budget-scenarios/<scenario_id>/approve")
def approve_scenario(scenario_id):
    user_id = authenticate((ANALYTICS_LEAD,))
    scenario = must("budget_scenarios", scenario_id)
    return ok(perform_approve(scenario, user_id))


# -------------------------------------------------------- budget allocations

@bp.post("/mmm/budget-allocations")
def create_allocation():
    authenticate((BRAND_PLANNER,))
    body = get_body()
    baseline_spend_cents = field_int(body, "baseline_spend_cents", minimum=0)

    scenario = must_field("budget_scenarios", body, "budget_scenario_id")
    channel = must_field("media_channels", body, "channel_id")

    if channel["status"] == "RETIRED":
        raise ApiError("ERR_CHANNEL_RETIRED",
                       "A RETIRED channel may not hold an allocation row.")

    run = db.model_runs.get(scenario["model_run_id"])
    if channel["market_id"] != scenario["market_id"]:
        raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                       "Channel %s does not belong to the scenario's market."
                       % channel["channel_code"])
    if run is None or channel["id"] not in run["included_channel_ids"]:
        raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                       "Channel %s is absent from the referenced run's inclusion list."
                       % channel["channel_code"])

    for existing in store.allocations_of_scenario(scenario["id"]):
        if existing["channel_id"] == channel["id"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "That channel already holds an allocation row on this scenario.")

    row = base_row("budget_allocations")
    row.update({
        "budget_scenario_id": scenario["id"],
        "channel_id": channel["id"],
        "baseline_spend_cents": baseline_spend_cents,
        "allocated_cents": baseline_spend_cents,
        "shifted_cents": 0,
        "projected_contribution_units": Decimal("0.0000"),
        "constraint_binding": "NONE",
    })
    db.add("budget_allocations", row)
    refresh_allocation_totals(scenario)
    return created(row)


@bp.get("/mmm/budget-allocations")
def list_allocations():
    authenticate(READ_ROLES)
    rows = db.all("budget_allocations")
    for param in ("budget_scenario_id", "channel_id", "constraint_binding"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(ordering.sort_rows("budget_allocations", rows), request.args)


@bp.get("/mmm/budget-allocations/<allocation_id>")
def get_allocation(allocation_id):
    authenticate(READ_ROLES)
    return ok(must("budget_allocations", allocation_id))
