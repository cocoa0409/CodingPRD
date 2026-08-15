"""SurchargeSchedule endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, parse_period, make_entity, lookup, list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INDEX_NOT_PUBLISHED, ERR_NOT_FOUND,
)
from services.calculations import compute_surcharge_cents

bp = Blueprint("surcharge_schedules", __name__)


def _find_index(plant_id, ingredient, period):
    for ix in DB.ingredient_indices.values():
        if (
            ix.get("plant_id") == plant_id
            and ix.get("ingredient") == ingredient
            and ix.get("period") == period
        ):
            return ix
    return None


@bp.route("/bakery/surcharge-schedules", methods=["POST"])
def create_schedule():
    _, role = get_auth()
    require_role(role, {"PricingAnalyst"})
    data = body()
    product_id = req_string(data, "product_id")
    product = lookup(DB.products, product_id, "product")
    period = req_string(data, "period")
    parse_period(period, "period")

    # unique per (product, period)
    for s in DB.surcharge_schedules.values():
        if s.get("product_id") == product_id and s.get("period") == period:
            raise ApiError(ERR_INVALID_REQUEST, "Schedule already exists for (product, period)", 400)

    plant = DB.plants.get(product.get("plant_id"))
    if plant is None:
        raise ApiError(ERR_NOT_FOUND, "plant not found", 404)

    flour_ix = _find_index(plant["id"], "FLOUR", period)
    butter_ix = _find_index(plant["id"], "BUTTER", period)
    if flour_ix is None or butter_ix is None:
        raise ApiError(ERR_INDEX_NOT_PUBLISHED, "Required FLOUR/BUTTER index missing for period", 409)
    if flour_ix.get("status") != "FORECAST" or butter_ix.get("status") != "FORECAST":
        raise ApiError(ERR_INDEX_NOT_PUBLISHED, "Required indices must be FORECAST at creation", 409)

    provisional = compute_surcharge_cents(
        product, plant, flour_ix["forecast_value"], butter_ix["forecast_value"]
    )

    sched = make_entity({
        "product_id": product_id,
        "period": period,
        "provisional_surcharge_cents": provisional,
        "final_surcharge_cents": None,
        "status": "PROVISIONAL",
    })
    DB.surcharge_schedules[sched["id"]] = sched
    return success_object(public(sched), status=201)


@bp.route("/bakery/surcharge-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    get_auth()
    sched = lookup(DB.surcharge_schedules, sid, "surcharge schedule")
    return success_object(public(sched))


@bp.route("/bakery/surcharge-schedules", methods=["GET"])
def list_schedules():
    get_auth()
    filters = {
        "product_id": request.args.get("product_id"),
        "period": request.args.get("period"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB.surcharge_schedules.values()), filters)
