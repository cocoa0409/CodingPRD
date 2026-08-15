"""ProductionForecast list/get/lock endpoints."""
from flask import Blueprint

from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import get_forecast, get_period, ser, touch
from routes.common import list_endpoint

bp = Blueprint("forecasts", __name__)


@bp.get("/production-forecasts")
def list_forecasts():
    return list_endpoint(
        "forecasts",
        [
            ("meal_period_id", "meal_period_id"),
            ("recipe_id", "recipe_id"),
            ("status", "status"),
            ("variant", "variant"),
        ],
    )


@bp.get("/production-forecasts/<fid>")
def get_one_forecast(fid):
    auth(ALL_ROLES)
    return ok(ser(get_forecast(fid)))


@bp.post("/production-forecasts/<fid>/lock")
def lock_forecast(fid):
    auth(["KitchenLead"])
    forecast = get_forecast(fid)
    if forecast["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Forecast is not DRAFT")
    period = get_period(forecast["meal_period_id"])
    if period["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_FORECAST_LOCKED_PERIOD", 409, "Period is no longer SCHEDULED"
        )
    forecast["status"] = "LOCKED"
    touch(forecast)
    return ok(ser(forecast))
