"""Pipeline drug registry and spend forecast endpoints (PRD 3.8)."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from routes.helpers import (
    get_body, get_or_404, list_response, public, read_all, req_date,
    req_enum, req_int, req_num, req_str, stamp_new,
)
from services.forecast import run_forecast
from util import new_id

bp = Blueprint("pipeline", __name__)

FORECAST_VARIANTS = ("BASELINE", "POLICY_ADJUSTED")


@bp.post("/api/pipeline-drugs")
def create_pipeline_drug():
    authorized(["PlanAdmin"])
    body = get_body()
    drug_name = req_str(body, "drug_name")
    expected_approval_date = req_date(body, "expected_approval_date")
    prevalence_per_100k = req_num(body, "prevalence_per_100k", gt=0)
    projected_annual_cost_cents = req_int(body, "projected_annual_cost_cents", min_v=1)
    year1_uptake_pct = req_num(body, "year1_uptake_pct", gt=0, le=1)
    steady_state_uptake_pct = req_num(body, "steady_state_uptake_pct", gt=0, le=1)
    biosimilar_erosion_pct = req_num(body, "biosimilar_erosion_pct", ge=0, lt=1)
    rec = {
        "id": new_id(),
        "drug_name": drug_name,
        "expected_approval_date": expected_approval_date.isoformat(),
        "prevalence_per_100k": prevalence_per_100k,
        "projected_annual_cost_cents": projected_annual_cost_cents,
        "year1_uptake_pct": year1_uptake_pct,
        "steady_state_uptake_pct": steady_state_uptake_pct,
        "biosimilar_erosion_pct": biosimilar_erosion_pct,
    }
    stamp_new(rec)
    db["pipeline_drugs"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.get("/api/pipeline-drugs")
def list_pipeline_drugs():
    read_all()
    return list_response(list(db["pipeline_drugs"].values()))


@bp.get("/api/pipeline-drugs/<pipelineDrugId>")
def get_pipeline_drug(pipelineDrugId):
    read_all()
    return success_object(public(get_or_404("pipeline_drugs", pipelineDrugId)))


@bp.post("/api/spend-forecasts")
def create_forecast():
    authorized(["PharmacyAnalyst"])
    body = get_body()
    variant = req_enum(body, "variant", FORECAST_VARIANTS)
    horizon_years = req_int(body, "horizon_years", min_v=1, max_v=5)
    enrollment_projection = req_int(body, "enrollment_projection", min_v=1)
    computed = run_forecast(variant, horizon_years, enrollment_projection)
    # immutable computed snapshot: id + created_at only (no updated_at/version)
    rec = {
        "id": new_id(),
        "variant": variant,
        "horizon_years": horizon_years,
        "enrollment_projection": enrollment_projection,
        "as_of_date": computed["as_of_date"],
        "pipeline_total_cents": computed["pipeline_total_cents"],
        "inline_annualized_cents": computed["inline_annualized_cents"],
        "total_projected_cents": computed["total_projected_cents"],
        "per_drug_projections": computed["per_drug_projections"],
    }
    stamp_new(rec, common=False)
    db["spend_forecasts"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.get("/api/spend-forecasts/<forecastId>")
def get_forecast(forecastId):
    read_all()
    return success_object(public(get_or_404("spend_forecasts", forecastId)))
