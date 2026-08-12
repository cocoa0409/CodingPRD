"""Tour lifecycle endpoints (PRD 3.1, 3.6, 3.8) and computed tour P&L."""
from flask import Blueprint

from db import store, new_entity, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body, v_str, v_date,
)
from response import success_object, list_response
from services import tour_json, resolve_tour, settlement_for_show

bp = Blueprint("tours", __name__)

TM_ONLY = frozenset({ROLE_TOUR_MANAGER})


@bp.post("/tours")
def create_tour():
    authenticate(TM_ONLY)
    b = get_body()
    tour_name = v_str(b, "tour_name")
    artist_name = v_str(b, "artist_name")
    ws = v_date(b, "window_start_date")
    we = v_date(b, "window_end_date")
    # The window end must fall strictly after the window start (PRD 3.1).
    if we <= ws:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "window_end_date must be strictly after window_start_date",
        )
    t = new_entity()
    t.update(
        {
            "tour_name": tour_name,
            "artist_name": artist_name,
            "window_start_date": ws.isoformat(),
            "window_end_date": we.isoformat(),
            "posture": "OPEN",
            "projected_gross_cents": 0,
            "projected_cost_cents": 0,
            "settled_gross_cents": 0,
            "settled_cost_cents": 0,
            "status": "PLANNING",
        }
    )
    store["tours"][t["id"]] = t
    return success_object(tour_json(t), 201)


@bp.get("/tours")
def list_tours():
    authenticate(READ_ROLES)
    return list_response(list(store["tours"].values()), tour_json)


@bp.get("/tours/<tourId>")
def get_tour(tourId):
    authenticate(READ_ROLES)
    return success_object(tour_json(resolve_tour(tourId)))


@bp.post("/tours/<tourId>/start-routing")
def start_routing(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    if t["status"] != "PLANNING":
        raise ApiError(
            "ERR_TOUR_NOT_PLANNING", 409, "start-routing requires Tour.status == PLANNING"
        )
    has_market = any(m["tour_id"] == t["id"] for m in store["markets"].values())
    has_venue = any(v["tour_id"] == t["id"] for v in store["venues"].values())
    if not (has_market and has_venue):
        raise ApiError(
            "ERR_TOUR_UNSTAGED",
            409,
            "start-routing requires at least one Market and one Venue",
        )
    t["status"] = "ROUTING"
    touch(t)
    return success_object(tour_json(t))


@bp.post("/tours/<tourId>/open-on-sale")
def open_on_sale(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    if t["status"] != "ROUTING":
        raise ApiError("ERR_INVALID_STATE", 409, "open-on-sale requires Tour.status == ROUTING")
    has_confirmed = any(
        s["tour_id"] == t["id"] and s["status"] == "CONFIRMED"
        for s in store["shows"].values()
    )
    if not has_confirmed:
        raise ApiError(
            "ERR_NO_CONFIRMED_SHOWS", 409, "open-on-sale requires >= 1 CONFIRMED show"
        )
    if t["posture"] != "OPEN":
        raise ApiError(
            "ERR_POSTURE_NOT_OPEN", 409, "Operation requires Tour.posture == OPEN"
        )
    t["status"] = "ON_SALE"
    touch(t)
    return success_object(tour_json(t))


@bp.post("/tours/<tourId>/enter-settlement-review")
def enter_settlement_review(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    if t["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "enter-settlement-review requires Tour.status == IN_PROGRESS",
        )
    pending = any(
        s["tour_id"] == t["id"] and s["status"] not in ("SETTLED", "CANCELLED")
        for s in store["shows"].values()
    )
    if pending:
        raise ApiError(
            "ERR_SHOWS_PENDING",
            409,
            "Tour has shows in non-terminal status blocking transition",
        )
    t["status"] = "SETTLEMENT_REVIEW"
    touch(t)
    return success_object(tour_json(t))


@bp.post("/tours/<tourId>/close")
def close_tour(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    if t["status"] != "SETTLEMENT_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "close requires Tour.status == SETTLEMENT_REVIEW"
        )
    for s in store["shows"].values():
        if s["tour_id"] != t["id"] or s["status"] == "CANCELLED":
            continue
        st = settlement_for_show(s["id"])
        if st is not None and st["status"] != "PAID":
            raise ApiError(
                "ERR_SETTLEMENTS_OPEN",
                409,
                "Tour has settlement rows not in PAID state",
            )
    outstanding = any(
        h["tour_id"] == t["id"] and h["status"] == "ACTIVE"
        for h in store["compliance_holds"].values()
    )
    if outstanding:
        raise ApiError(
            "ERR_HOLDS_OUTSTANDING",
            409,
            "Tour has ACTIVE ComplianceHold rows blocking close",
        )
    t["status"] = "CLOSED"
    touch(t)
    return success_object(tour_json(t))


@bp.get("/tours/<tourId>/pnl")
def tour_pnl(tourId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    return success_object(
        {
            "projected_gross_cents": t["projected_gross_cents"],
            "projected_cost_cents": t["projected_cost_cents"],
            "settled_gross_cents": t["settled_gross_cents"],
            "settled_cost_cents": t["settled_cost_cents"],
        }
    )
