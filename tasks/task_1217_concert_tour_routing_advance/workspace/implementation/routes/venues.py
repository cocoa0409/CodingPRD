"""Venue endpoints (PRD 3.1): nested CRUD plus flat fetch/search."""
import re

from flask import Blueprint, request

from db import store, new_entity
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body,
    v_str, v_int, v_date_list,
)
from response import success_object, list_response
from services import venue_json, resolve_tour, resolve_venue

bp = Blueprint("venues", __name__)

_CURFEW_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@bp.post("/tours/<tourId>/venues")
def create_venue(tourId):
    authenticate(frozenset({ROLE_TOUR_MANAGER}))
    t = resolve_tour(tourId)
    b = get_body()
    market_id = v_str(b, "market_id")
    market = store["markets"].get(market_id)
    if market is None or market["tour_id"] != t["id"]:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "market_id does not resolve within the same tour",
        )
    venue_name = v_str(b, "venue_name")
    capacity = v_int(b, "capacity", minv=1)  # sellable capacity must be > 0
    base_rent_cents = v_int(b, "base_rent_cents", minv=0)
    curfew_local_time = v_str(b, "curfew_local_time")
    if not _CURFEW_RE.match(curfew_local_time):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "curfew_local_time must be in HH:MM form"
        )
    available_dates = v_date_list(b, "available_dates")
    # (market_id, venue_name) unique within the tour (ERR_DUPLICATE_KEY).
    for v in store["venues"].values():
        if (
            v["tour_id"] == t["id"]
            and v["market_id"] == market_id
            and v["venue_name"] == venue_name
        ):
            raise ApiError(
                "ERR_DUPLICATE_KEY",
                409,
                "venue_name must be unique within the market for this tour",
            )
    v = new_entity()
    v.update(
        {
            "tour_id": t["id"],
            "market_id": market_id,
            "venue_name": venue_name,
            "capacity": capacity,
            "base_rent_cents": base_rent_cents,
            "curfew_local_time": curfew_local_time,
            "available_dates": available_dates,
            "booked_dates": [],
        }
    )
    store["venues"][v["id"]] = v
    return success_object(venue_json(v), 201)


@bp.get("/tours/<tourId>/venues")
def list_venues(tourId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    market_id = request.args.get("market_id")
    items = [v for v in store["venues"].values() if v["tour_id"] == t["id"]]
    if market_id is not None:
        items = [v for v in items if v["market_id"] == market_id]
    return list_response(items, venue_json)


@bp.get("/tours/<tourId>/venues/<venueId>")
def get_venue(tourId, venueId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    return success_object(venue_json(resolve_venue(t, venueId)))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/venues/<venueId>")
def flat_get_venue(venueId):
    authenticate(READ_ROLES)
    v = store["venues"].get(venueId)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Venue not found")
    return success_object(venue_json(v))


@bp.get("/tours/venues")
def flat_search_venues():
    authenticate(READ_ROLES)
    tour_id = request.args.get("tour_id")
    market_id = request.args.get("market_id")
    items = list(store["venues"].values())
    if tour_id is not None:
        items = [v for v in items if v["tour_id"] == tour_id]
    if market_id is not None:
        items = [v for v in items if v["market_id"] == market_id]
    return list_response(items, venue_json)
