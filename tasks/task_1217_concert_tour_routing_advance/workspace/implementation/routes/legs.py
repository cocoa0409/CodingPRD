"""RoutingLeg endpoints (PRD 3.2): create/list/get, lock/complete/cancel,
plus flat fetch/search."""
from datetime import datetime, time as dtime, timezone

from flask import Blueprint, request

from db import store, clock, new_entity, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body,
    v_str, v_int, v_date, parse_date,
)
from response import success_object, list_response
from services import (
    leg_json, resolve_tour, resolve_leg,
    compute_drive_minutes, compute_crew_rest_required,
    recompute_tour_posture,
)

bp = Blueprint("legs", __name__)

TM_ONLY = frozenset({ROLE_TOUR_MANAGER})


@bp.post("/tours/<tourId>/routing-legs")
def create_leg(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    b = get_body()
    from_market_id = v_str(b, "from_market_id")
    to_market_id = v_str(b, "to_market_id")
    travel_date = v_date(b, "travel_date")
    drive_miles = v_int(b, "drive_miles", minv=0)
    leg_index = v_int(b, "leg_index")
    for mid in (from_market_id, to_market_id):
        m = store["markets"].get(mid)
        if m is None or m["tour_id"] != t["id"]:
            raise ApiError(
                "ERR_REFERENTIAL_INTEGRITY",
                422,
                "from_market_id and to_market_id must resolve within the same tour",
            )
    # leg_index must be unique per tour (ERR_DUPLICATE_KEY).
    for l in store["legs"].values():
        if l["tour_id"] == t["id"] and l["leg_index"] == leg_index:
            raise ApiError(
                "ERR_DUPLICATE_KEY", 409, "leg_index must be unique within the tour"
            )
    drive_minutes = compute_drive_minutes(drive_miles)
    leg = new_entity()
    leg.update(
        {
            "tour_id": t["id"],
            "from_market_id": from_market_id,
            "to_market_id": to_market_id,
            "travel_date": travel_date.isoformat(),
            "drive_miles": drive_miles,
            "drive_minutes": drive_minutes,
            "crew_rest_required": compute_crew_rest_required(drive_minutes),
            "leg_index": leg_index,
            "status": "PLANNED",
        }
    )
    store["legs"][leg["id"]] = leg
    return success_object(leg_json(leg), 201)


@bp.get("/tours/<tourId>/routing-legs")
def list_legs(tourId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    items = [l for l in store["legs"].values() if l["tour_id"] == t["id"]]
    return list_response(items, leg_json)


@bp.get("/tours/<tourId>/routing-legs/<legId>")
def get_leg(tourId, legId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    return success_object(leg_json(resolve_leg(t, legId)))


@bp.post("/tours/<tourId>/routing-legs/<legId>/lock")
def lock_leg(tourId, legId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    leg = resolve_leg(t, legId)
    if leg["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "lock requires RoutingLeg.status == PLANNED")
    # Anchoring: origin and destination markets must each contain at least
    # one CONFIRMED show. The entity model carries no ferry-leg flag, so the
    # non-production ferry-leg waiver is not reachable through the API.
    for mid in (leg["from_market_id"], leg["to_market_id"]):
        anchored = any(
            s["tour_id"] == t["id"]
            and s["market_id"] == mid
            and s["status"] == "CONFIRMED"
            for s in store["shows"].values()
        )
        if not anchored:
            raise ApiError(
                "ERR_LEG_UNANCHORED",
                409,
                "Routing leg's origin/destination markets contain no CONFIRMED show",
            )
    # Crew rest: if this leg requires rest, every adjacent (by leg_index)
    # already-LOCKED leg must be separated by at least one full rest day
    # (>= 2 calendar days between travel dates).
    if leg["crew_rest_required"]:
        travel = parse_date(leg["travel_date"])
        for other in store["legs"].values():
            if (
                other["tour_id"] == t["id"]
                and other["id"] != leg["id"]
                and other["status"] == "LOCKED"
                and abs(other["leg_index"] - leg["leg_index"]) == 1
            ):
                gap = abs((parse_date(other["travel_date"]) - travel).days)
                if gap < 2:
                    raise ApiError(
                        "ERR_REST_VIOLATION",
                        409,
                        "Crew rest-day requirement violated by locked leg",
                    )
    leg["status"] = "LOCKED"
    touch(leg)
    # Locking recalculates the tour's posture (SCAFFOLD 1.2 side effect).
    if recompute_tour_posture(t):
        touch(t)
    return success_object(leg_json(leg))


@bp.post("/tours/<tourId>/routing-legs/<legId>/complete")
def complete_leg(tourId, legId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    leg = resolve_leg(t, legId)
    if leg["status"] != "LOCKED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "complete requires RoutingLeg.status == LOCKED"
        )
    travel_midnight = datetime.combine(
        parse_date(leg["travel_date"]), dtime.min, tzinfo=timezone.utc
    )
    if clock["now"] < travel_midnight:
        raise ApiError(
            "ERR_LEG_NOT_YET", 409, "Cannot complete a leg before its travel_date"
        )
    leg["status"] = "COMPLETED"
    touch(leg)
    return success_object(leg_json(leg))


@bp.post("/tours/<tourId>/routing-legs/<legId>/cancel")
def cancel_leg(tourId, legId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    leg = resolve_leg(t, legId)
    if leg["status"] != "PLANNED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "cancel requires RoutingLeg.status == PLANNED"
        )
    leg["status"] = "CANCELLED"
    touch(leg)
    return success_object(leg_json(leg))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/routing-legs/<legId>")
def flat_get_leg(legId):
    authenticate(READ_ROLES)
    leg = store["legs"].get(legId)
    if leg is None:
        raise ApiError("ERR_NOT_FOUND", 404, "RoutingLeg not found")
    return success_object(leg_json(leg))


@bp.get("/tours/routing-legs")
def flat_search_legs():
    authenticate(READ_ROLES)
    tour_id = request.args.get("tour_id")
    from_market_id = request.args.get("from_market_id")
    to_market_id = request.args.get("to_market_id")
    items = list(store["legs"].values())
    if tour_id is not None:
        items = [l for l in items if l["tour_id"] == tour_id]
    if from_market_id is not None:
        items = [l for l in items if l["from_market_id"] == from_market_id]
    if to_market_id is not None:
        items = [l for l in items if l["to_market_id"] == to_market_id]
    return list_response(items, leg_json)
