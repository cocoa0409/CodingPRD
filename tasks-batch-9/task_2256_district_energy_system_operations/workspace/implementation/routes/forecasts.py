"""LoadForecast endpoints and the publish projection (PRD 3.4)."""

from flask import Blueprint

import calc
import enums
import services as svc
from db import base_record, store, touch
from errors import fail
from middleware import endpoint, paginate
from validators import (bad, get_dt, get_enum, get_num, get_str, json_body,
                        query_enum, query_str)

bp = Blueprint("forecasts", __name__, url_prefix="/district-energy")

READERS = ("SystemController", "DispatchOperator", "NetworkEngineer", "BillingAnalyst")


def forecast_input_set(forecast):
    """Agreements live on the loop across the forecast's service instant."""
    moment = forecast["_service_date"]
    result = []
    for agreement in svc.rows("agreements"):
        if agreement["loop_id"] != forecast["loop_id"]:
            continue
        if agreement["contract_state"] != "ACTIVE":
            continue
        if agreement["_service_start_date"] > moment:
            continue
        if agreement["_service_end_date"] <= moment:
            continue
        result.append(agreement)
    return result


@endpoint(bp, "/load-forecasts", ["POST"], ["DispatchOperator"], status=201)
def create_forecast():
    body = json_body()
    loop_id = get_str(body, "loop_id")
    service_raw, service_dt = get_dt(body, "service_date")
    occupancy_profile = get_enum(body, "occupancy_profile", enums.OCCUPANCY_PROFILE)
    hdh = get_num(body, "heating_degree_hours", required=False, default=0.0, ge=0)
    cdh = get_num(body, "cooling_degree_hours", required=False, default=0.0, ge=0)
    actual_hdh = get_num(body, "actual_heating_degree_hours", required=False,
                         default=None, ge=0)
    actual_cdh = get_num(body, "actual_cooling_degree_hours", required=False,
                         default=None, ge=0)

    loop = svc.fk_get("loops", loop_id)

    forecast = base_record()
    forecast.update({
        "loop_id": loop["id"],
        "service_date": service_raw,
        "_service_date": service_dt,
        "heating_degree_hours": hdh,
        "cooling_degree_hours": cdh,
        "actual_heating_degree_hours": actual_hdh,
        "actual_cooling_degree_hours": actual_cdh,
        "occupancy_profile": occupancy_profile,
        "variant_applied": None,
        "coincident_demand_kw": 0.0,
        "projected_energy_mwh": 0.0,
        "contributing_agreement_count": 0,
        "forecast_state": "DRAFT",
    })
    store.forecasts[forecast["id"]] = forecast
    return forecast


@endpoint(bp, "/load-forecasts", ["GET"], READERS)
def list_forecasts():
    filters = {}
    loop_id = query_str("loop_id")
    forecast_state = query_enum("forecast_state", enums.FORECAST_STATE)
    variant_applied = query_enum("variant_applied", enums.FORECAST_VARIANT)
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if forecast_state is not None:
        filters["forecast_state"] = forecast_state
    if variant_applied is not None:
        filters["variant_applied"] = variant_applied
    return paginate(svc.where("forecasts", **filters))


@endpoint(bp, "/load-forecasts/<forecast_id>", ["GET"], READERS)
def get_forecast(forecast_id):
    return svc.path_get("forecasts", forecast_id)


@endpoint(bp, "/load-forecasts/<forecast_id>/publish", ["POST"], ["DispatchOperator"])
def publish_forecast(forecast_id):
    body = json_body()
    variant = get_enum(body, "variant", enums.FORECAST_VARIANT)
    actual_hdh = get_num(body, "actual_heating_degree_hours", required=False,
                         default=None, ge=0)
    actual_cdh = get_num(body, "actual_cooling_degree_hours", required=False,
                         default=None, ge=0)

    forecast = svc.path_get("forecasts", forecast_id)
    if forecast["forecast_state"] != "DRAFT":
        fail("ERR_FORECAST_STATE_INVALID",
             "only a DRAFT forecast can be published")

    if actual_hdh is not None:
        forecast["actual_heating_degree_hours"] = actual_hdh
    if actual_cdh is not None:
        forecast["actual_cooling_degree_hours"] = actual_cdh

    if variant == "ACTUAL_WEIGHTED_FINAL":
        if (forecast["actual_heating_degree_hours"] is None
                or forecast["actual_cooling_degree_hours"] is None):
            bad("the ACTUAL_WEIGHTED_FINAL variant requires both "
                "actual_heating_degree_hours and actual_cooling_degree_hours")

    projection = calc.forecast_load_projection(
        forecast, variant, forecast_input_set(forecast))
    forecast.update(projection)
    forecast["forecast_state"] = "PUBLISHED"
    touch(forecast)

    for peer in svc.rows("forecasts"):
        if peer["id"] == forecast["id"]:
            continue
        if peer["loop_id"] != forecast["loop_id"]:
            continue
        if peer["forecast_state"] != "PUBLISHED":
            continue
        if peer["_service_date"] != forecast["_service_date"]:
            continue
        peer["forecast_state"] = "SUPERSEDED"
        touch(peer)

    return forecast
