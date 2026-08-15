"""High-cost claimant forecast endpoints (PRD §3.9)."""
from flask import Blueprint, request

from middleware import authorized
from response import success_object
from routes.helpers import READ_FORECAST, get_one, list_response
from services.accumulation import compute_forecast
from services.core import new_record, public
from util import CLOCK
from validate import get_body, req_str, req_int, req_enum, require_ref

bp = Blueprint("forecasts", __name__)

FORECAST_BASES = {"PURE_EXPERIENCE", "CREDIBILITY_WEIGHTED"}


@bp.post("/stop-loss/forecasts")
def create_forecast():
    authorized(["PlanAdministrator", "StopLossAnalyst"])
    body = get_body()
    plan_id = req_str(body, "plan_id")
    forecast_basis = req_enum(body, "forecast_basis", FORECAST_BASES)
    next_ded = req_int(body, "next_year_specific_deductible_cents", minimum=0)
    plan = require_ref("plans", plan_id, "plan_id")

    now = CLOCK.now()
    projected_excess, projected_count = compute_forecast(
        plan, forecast_basis, next_ded, now)
    rec = new_record("forecasts", {
        "plan_id": plan_id,
        "forecast_basis": forecast_basis,
        "next_year_specific_deductible_cents": next_ded,
        "projected_excess_cents": projected_excess,
        "projected_member_count": projected_count,
        "computed_at": CLOCK.now_iso(),
    })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/forecasts/<rid>")
def get_forecast(rid):
    return get_one("forecasts", rid, READ_FORECAST)


@bp.get("/stop-loss/forecasts")
def list_forecasts():
    return list_response("forecasts", READ_FORECAST,
                         {"plan_id": request.args.get("plan_id")})
