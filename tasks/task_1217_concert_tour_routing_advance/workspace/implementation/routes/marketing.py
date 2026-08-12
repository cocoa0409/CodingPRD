"""MarketingSpend endpoints (PRD 3.6): create/list/get plus flat fetch/search.
cpa_cents = round_half_up(spend_cents / attributed_ticket_sales); null when
attributed_ticket_sales == 0."""
from flask import Blueprint, request

from db import store, new_entity
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body,
    v_int, v_enum, v_date,
)
from response import success_object, list_response
from services import (
    MARKETING_CHANNELS, spend_json, resolve_tour, resolve_show, resolve_spend,
    compute_cpa_cents,
)

bp = Blueprint("marketing", __name__)


@bp.post("/tours/<tourId>/shows/<showId>/marketing-spends")
def create_spend(tourId, showId):
    authenticate(frozenset({ROLE_TOUR_MANAGER}))
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    b = get_body()
    channel = v_enum(b, "channel", MARKETING_CHANNELS)
    spend_cents = v_int(b, "spend_cents", minv=0)
    flight_start = v_date(b, "flight_start_date")
    flight_end = v_date(b, "flight_end_date")
    attributed = v_int(b, "attributed_ticket_sales", minv=0)
    m = new_entity()
    m.update(
        {
            "show_id": s["id"],
            "channel": channel,
            "spend_cents": spend_cents,
            "flight_start_date": flight_start.isoformat(),
            "flight_end_date": flight_end.isoformat(),
            "attributed_ticket_sales": attributed,
            "cpa_cents": compute_cpa_cents(spend_cents, attributed),
        }
    )
    store["spends"][m["id"]] = m
    return success_object(spend_json(m), 201)


@bp.get("/tours/<tourId>/shows/<showId>/marketing-spends")
def list_spends(tourId, showId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    channel = request.args.get("channel")
    items = [m for m in store["spends"].values() if m["show_id"] == s["id"]]
    if channel is not None:
        items = [m for m in items if m["channel"] == channel]
    return list_response(items, spend_json)


@bp.get("/tours/<tourId>/shows/<showId>/marketing-spends/<spendId>")
def get_spend(tourId, showId, spendId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    return success_object(spend_json(resolve_spend(s, spendId)))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/marketing-spends/<spendId>")
def flat_get_spend(spendId):
    authenticate(READ_ROLES)
    m = store["spends"].get(spendId)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", 404, "MarketingSpend not found")
    return success_object(spend_json(m))


@bp.get("/tours/marketing-spends")
def flat_search_spends():
    authenticate(READ_ROLES)
    show_id = request.args.get("show_id")
    items = list(store["spends"].values())
    if show_id is not None:
        items = [m for m in items if m["show_id"] == show_id]
    return list_response(items, spend_json)
