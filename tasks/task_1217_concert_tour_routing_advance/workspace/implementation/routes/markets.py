"""Market endpoints (PRD 3.1): nested CRUD plus flat fetch/search."""
from flask import Blueprint, request

from db import store, new_entity
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body,
    v_str, v_int,
)
from errors import ApiError
from response import success_object, list_response
from services import market_json, resolve_tour, resolve_market

bp = Blueprint("markets", __name__)


@bp.post("/tours/<tourId>/markets")
def create_market(tourId):
    authenticate(frozenset({ROLE_TOUR_MANAGER}))
    t = resolve_tour(tourId)
    b = get_body()
    market_code = v_str(b, "market_code")
    metro_name = v_str(b, "metro_name")
    country_code = v_str(b, "country_code")
    radius_miles = v_int(b, "radius_miles", minv=0)
    exclusivity_window_days = v_int(b, "exclusivity_window_days", minv=0)
    territory_rank = v_int(b, "territory_rank")
    # territory_rank must be unique within the tour (ERR_DUPLICATE_KEY).
    for m in store["markets"].values():
        if m["tour_id"] == t["id"] and m["territory_rank"] == territory_rank:
            raise ApiError(
                "ERR_DUPLICATE_KEY",
                409,
                "territory_rank must be unique within the tour",
            )
    m = new_entity()
    m.update(
        {
            "tour_id": t["id"],
            "market_code": market_code,
            "metro_name": metro_name,
            "country_code": country_code,
            "radius_miles": radius_miles,
            "exclusivity_window_days": exclusivity_window_days,
            "territory_rank": territory_rank,
        }
    )
    store["markets"][m["id"]] = m
    return success_object(market_json(m), 201)


@bp.get("/tours/<tourId>/markets")
def list_markets(tourId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    items = [m for m in store["markets"].values() if m["tour_id"] == t["id"]]
    return list_response(items, market_json)


@bp.get("/tours/<tourId>/markets/<marketId>")
def get_market(tourId, marketId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    return success_object(market_json(resolve_market(t, marketId)))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/markets/<marketId>")
def flat_get_market(marketId):
    authenticate(READ_ROLES)
    m = store["markets"].get(marketId)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Market not found")
    return success_object(market_json(m))


@bp.get("/tours/markets")
def flat_search_markets():
    authenticate(READ_ROLES)
    tour_id = request.args.get("tour_id")
    items = list(store["markets"].values())
    if tour_id is not None:
        items = [m for m in items if m["tour_id"] == tour_id]
    return list_response(items, market_json)
