"""PromoterHold endpoints (PRD 3.3): place/list/get, counter, respond-counter,
accept, reject, withdraw, plus flat fetch/search.

Expiry: the expiry sweep runs on every hold state transition and on every
logical-clock advance (PRD 3.3). On accept/counter/respond-counter, a hold
that is expired at request time is rejected with ERR_HOLD_EXPIRED (the
expiry precondition on those transitions); other transitions on a terminal
hold yield ERR_INVALID_STATE.
"""
from datetime import timedelta

from flask import Blueprint, request

from db import store, clock, new_entity, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, ROLE_PROMOTER, get_body,
    v_str, v_int, v_bool, parse_dt, fmt_dt,
)
from response import success_object, list_response
from services import (
    HOLD_TTL_HOURS, COUNTER_EXTENSION_HOURS, MAX_COUNTER_ROUNDS,
    hold_json, resolve_tour, resolve_show, resolve_hold, sweep_hold,
)

bp = Blueprint("holds", __name__)

PROMOTER_ONLY = frozenset({ROLE_PROMOTER})


def _guarded_hold(tourId, showId, holdId):
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    h = resolve_hold(s, holdId)
    sweep_hold(h)  # the expiry sweep runs on every state transition of a hold
    return t, s, h


def _require_unexpired(h):
    # The expiry sweep (PRD 3.3) moves a hold to EXPIRED at the instant the
    # clock reaches hold_expires_at, before any transition handler runs. An
    # EXPIRED hold is therefore caught by the permissible-state check
    # (PRD 2.10, priority 6) as ERR_INVALID_STATE, ahead of the expiry domain
    # rule (priority 8); ERR_HOLD_EXPIRED covers a hold whose expiry instant
    # has arrived but whose status is still PENDING/COUNTERED.
    if h["status"] != "EXPIRED" and clock["now"] >= parse_dt(h["hold_expires_at"]):
        raise ApiError("ERR_HOLD_EXPIRED", 409, "Logical clock >= hold_expires_at")


@bp.post("/tours/<tourId>/shows/<showId>/holds")
def place_hold(tourId, showId):
    authenticate(PROMOTER_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    b = get_body()
    promoter_name = v_str(b, "promoter_name")
    guarantee_cents = v_int(b, "guarantee_cents", minv=0)
    versus_pct = v_int(b, "versus_pct", minv=0, maxv=100)
    h = new_entity()
    h.update(
        {
            "show_id": s["id"],
            "promoter_name": promoter_name,
            # hold_expires_at = placed_at + 72h, placed on the logical clock.
            "hold_expires_at": fmt_dt(clock["now"] + timedelta(hours=HOLD_TTL_HOURS)),
            "guarantee_cents": guarantee_cents,
            "versus_pct": versus_pct,
            "counter_count": 0,
            "status": "PENDING",
            "_counter_guarantee_cents": None,
            "_counter_versus_pct": None,
        }
    )
    store["holds"][h["id"]] = h
    return success_object(hold_json(h), 201)


@bp.get("/tours/<tourId>/shows/<showId>/holds")
def list_holds(tourId, showId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    status = request.args.get("status")
    items = [h for h in store["holds"].values() if h["show_id"] == s["id"]]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    return list_response(items, hold_json)


@bp.get("/tours/<tourId>/shows/<showId>/holds/<holdId>")
def get_hold(tourId, showId, holdId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    return success_object(hold_json(resolve_hold(s, holdId)))


@bp.post("/tours/<tourId>/shows/<showId>/holds/<holdId>/counter")
def counter_hold(tourId, showId, holdId):
    authenticate(PROMOTER_ONLY)
    t, s, h = _guarded_hold(tourId, showId, holdId)
    b = get_body()
    guarantee_cents = v_int(b, "guarantee_cents", minv=0)
    versus_pct = v_int(b, "versus_pct", minv=0, maxv=100)
    # OCC gate (PRD 2.8): expected_show_version is non-optional.
    expected_show_version = v_int(b, "expected_show_version")
    if expected_show_version != s["version"]:
        raise ApiError(
            "ERR_STALE_SHOW_VERSION",
            412,
            "expected_show_version does not match Show.version",
        )
    _require_unexpired(h)
    if h["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "counter requires PromoterHold.status == PENDING")
    if h["counter_count"] >= MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_COUNTER_LIMIT", 409, "Hold has reached MAX_COUNTER_ROUNDS")
    h["status"] = "COUNTERED"
    h["counter_count"] += 1
    h["hold_expires_at"] = fmt_dt(
        parse_dt(h["hold_expires_at"]) + timedelta(hours=COUNTER_EXTENSION_HOURS)
    )
    # Countered terms are held aside; they replace the hold's terms only if
    # the manager accepts the counter via respond-counter (PRD 3.3).
    h["_counter_guarantee_cents"] = guarantee_cents
    h["_counter_versus_pct"] = versus_pct
    touch(h)
    # A successful counter increments the show's version by one.
    touch(s)
    return success_object(hold_json(h))


@bp.post("/tours/<tourId>/shows/<showId>/holds/<holdId>/respond-counter")
def respond_counter(tourId, showId, holdId):
    authenticate(frozenset({ROLE_TOUR_MANAGER}))
    t, s, h = _guarded_hold(tourId, showId, holdId)
    b = get_body()
    accept_counter = v_bool(b, "accept_counter")
    _require_unexpired(h)
    if h["status"] != "COUNTERED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "respond-counter requires PromoterHold.status == COUNTERED"
        )
    if accept_counter:
        # Terms are replaced by the countered values.
        if h["_counter_guarantee_cents"] is not None:
            h["guarantee_cents"] = h["_counter_guarantee_cents"]
            h["versus_pct"] = h["_counter_versus_pct"]
    # When false, the original terms stand and the promoter may counter again.
    h["status"] = "PENDING"
    h["_counter_guarantee_cents"] = None
    h["_counter_versus_pct"] = None
    touch(h)
    return success_object(hold_json(h))


@bp.post("/tours/<tourId>/shows/<showId>/holds/<holdId>/accept")
def accept_hold(tourId, showId, holdId):
    authenticate(PROMOTER_ONLY)
    t, s, h = _guarded_hold(tourId, showId, holdId)
    _require_unexpired(h)
    if h["status"] not in ("PENDING", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "accept requires PromoterHold.status in {PENDING, COUNTERED}",
        )
    if h["status"] == "PENDING" and s["status"] not in ("HOLD_REQUESTED", "HOLD_PLACED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "accept from PENDING requires Show.status in {HOLD_REQUESTED, HOLD_PLACED}",
        )
    h["status"] = "ACCEPTED"
    touch(h)
    # The first acceptance moves the show HOLD_REQUESTED -> HOLD_PLACED and
    # freezes the capacity snapshot / gross potential (PRD 3.3).
    if s["status"] == "HOLD_REQUESTED":
        venue = store["venues"][s["venue_id"]]
        s["status"] = "HOLD_PLACED"
        s["capacity"] = venue["capacity"]
        s["gross_potential_cents"] = s["capacity"] * s["avg_ticket_price_cents"]
        touch(s)
    return success_object(hold_json(h))


@bp.post("/tours/<tourId>/shows/<showId>/holds/<holdId>/reject")
def reject_hold(tourId, showId, holdId):
    authenticate(PROMOTER_ONLY)
    t, s, h = _guarded_hold(tourId, showId, holdId)
    if h["status"] not in ("PENDING", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "reject requires PromoterHold.status in {PENDING, COUNTERED}",
        )
    h["status"] = "REJECTED"
    touch(h)
    return success_object(hold_json(h))


@bp.post("/tours/<tourId>/shows/<showId>/holds/<holdId>/withdraw")
def withdraw_hold(tourId, showId, holdId):
    authenticate(PROMOTER_ONLY)
    t, s, h = _guarded_hold(tourId, showId, holdId)
    if h["status"] not in ("PENDING", "COUNTERED", "ACCEPTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "withdraw requires PromoterHold.status in {PENDING, COUNTERED, ACCEPTED}",
        )
    if s["status"] in ("ADVANCED", "PERFORMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "withdraw is not possible once the show is ADVANCED or PERFORMED",
        )
    was_accepted = h["status"] == "ACCEPTED"
    h["status"] = "WITHDRAWN"
    touch(h)
    if was_accepted and s["status"] == "HOLD_PLACED":
        # The show reverts HOLD_PLACED -> HOLD_REQUESTED and the show date is
        # released from the venue's booked calendar if it had been added.
        s["status"] = "HOLD_REQUESTED"
        venue = store["venues"][s["venue_id"]]
        if s["show_date"] in venue["booked_dates"]:
            venue["booked_dates"].remove(s["show_date"])
            touch(venue)
        touch(s)
    return success_object(hold_json(h))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/holds/<holdId>")
def flat_get_hold(holdId):
    authenticate(READ_ROLES)
    h = store["holds"].get(holdId)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PromoterHold not found")
    return success_object(hold_json(h))


@bp.get("/tours/holds")
def flat_search_holds():
    authenticate(READ_ROLES)
    show_id = request.args.get("show_id")
    items = list(store["holds"].values())
    if show_id is not None:
        items = [h for h in items if h["show_id"] == show_id]
    return list_response(items, hold_json)
