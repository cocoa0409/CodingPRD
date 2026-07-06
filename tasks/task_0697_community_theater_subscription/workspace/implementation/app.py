"""Community Theater Subscription API — Flask entry point.

All routes mount under /box-office (PRD §2). Storage is in-memory and starts
EMPTY on every boot (see db.py); no entity data is seeded anywhere.

Validation order (PRD §2.10), applied per request:
  1 header  -> 2 role -> 3 existence (left-to-right) -> 4 state -> 5 temporal
  -> 6 seat/accessibility -> 7 referential -> 8 fiscal -> 9 OCC.
"""
import os
from datetime import timedelta

from flask import Flask, request

import errors
from errors import ApiError, err
import services as svc
from auth import get_context, require_role
from db import store, parse_iso
from lookups import (
    get_season, get_production, get_performance, get_venue, get_seat,
    get_patron, get_subscription, get_ticket, get_donation, get_exchange,
    get_audition,
)
from response import success, error as error_response

app = Flask(__name__)

PREFIX = "/box-office"

ACCESS_SERVICES = {"NONE", "ASL", "AUDIO_DESCRIPTION", "OPEN_CAPTION"}
ACCESS_OFFERED = {"ASL", "AUDIO_DESCRIPTION", "OPEN_CAPTION"}
PRICE_TIERS = {"PREMIUM", "STANDARD", "VALUE"}
TICKET_ORIGINS = {"SINGLE", "SUBSCRIPTION"}
EXCHANGE_MODES = {"FLEX_PASS", "PAID_EXCHANGE"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route -> generic validation-style 404 envelope is not defined;
    # surface as a not-found-shaped error. Tests only hit defined routes.
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Serialization — stored dicts already match the public shape; return a copy.
# ---------------------------------------------------------------------------
def view(obj):
    return dict(obj)


def view_list(objs):
    return [dict(o) for o in objs]


def clock():
    return store.clock


# ---------------------------------------------------------------------------
# Ownership helper (PRD §2.1): Patron role's X-User-ID must equal the resource's
# patron foreign key. Opaque roles never compared.
# ---------------------------------------------------------------------------
def check_patron_owns(role, user_id, patron_id):
    if role == "Patron" and user_id != patron_id:
        raise err(errors.ERR_UNAUTHORIZED)


# ===========================================================================
# Clock (test-driving) — PRD §2.5
# ===========================================================================
@app.route(f"{PREFIX}/_clock/set_current_utc", methods=["POST"])
def clock_set():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    body = svc.body_or_400()
    to_iso = svc.req_iso(body, "to_iso8601")
    store.clock = parse_iso(to_iso)
    return success({"now_utc": to_iso}, status=200)


@app.route(f"{PREFIX}/_clock/sweep_holds", methods=["POST"])
def clock_sweep():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    swept = []
    affected = set()
    for t in store.tickets.values():
        if t["fulfillment_status"] != "HELD" or t["payment_status"] != "UNPAID":
            continue
        if t["hold_expires_at"] is None:
            continue
        if parse_iso(t["hold_expires_at"]) <= clock():
            t["fulfillment_status"] = "VOID"
            store.touch(t)
            swept.append(t["id"])
            affected.add(t["performance_id"])
    for pid in affected:
        perf = store.performances.get(pid)
        if perf is not None:
            svc.recompute_inventory(perf)
            store.touch(perf)
    return success({"swept_ticket_ids": swept}, status=200)


# ===========================================================================
# Seasons — PRD §3.1, §3.4
# ===========================================================================
@app.route(f"{PREFIX}/seasons", methods=["POST"])
def create_season():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    body = svc.body_or_400()
    name = svc.req_str(body, "name")
    opens = svc.req_iso(body, "renewal_window_opens_at")
    closes = svc.req_iso(body, "renewal_window_closes_at")
    base_fee = svc.req_int(body, "base_subscription_fee_cents", min_value=0)
    loyalty = svc.opt_number(body, "loyalty_renewal_discount_pct", default=0.10,
                             min_value=0)
    if not (loyalty < 1):
        raise err(errors.ERR_VALIDATION, "loyalty_renewal_discount_pct must be < 1")
    obj = {
        "id": store.new_id(),
        "name": name,
        "status": "PLANNING",
        "renewal_window_opens_at": opens,
        "renewal_window_closes_at": closes,
        "base_subscription_fee_cents": base_fee,
        "loyalty_renewal_discount_pct": loyalty,
        "released_seat_count": 0,
    }
    store.stamp_new(obj)
    store.seasons[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/seasons/<sid>", methods=["GET"])
def get_one_season(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    obj = get_season(sid)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/seasons", methods=["GET"])
def list_seasons():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    items = svc.sorted_by_created(store.seasons.values())
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/seasons/<sid>/open-renewal", methods=["POST"])
def season_open_renewal(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    season = get_season(sid)
    if season["status"] != "PLANNING":
        raise err(errors.ERR_INVALID_STATE)
    if clock() < parse_iso(season["renewal_window_opens_at"]):
        raise err(errors.ERR_RENEWAL_WINDOW_NOT_OPEN)
    # Side effect: ASSIGNED subscription seats on prior-season subscriptions ->
    # RENEWAL_OFFERED. The prior-season subscriptions are exactly those whose
    # season is this one (the season being opened reserves its own holders).
    for ss in store.subscription_seats.values():
        sub = store.subscriptions.get(ss["subscription_id"])
        if sub is None or sub["season_id"] != season["id"]:
            continue
        if sub["status"] == "ACTIVE" and ss["status"] == "ASSIGNED":
            ss["status"] = "RENEWAL_OFFERED"
            store.touch(ss)
    season["status"] = "RENEWAL_OPEN"
    store.touch(season)
    return success(view(season), status=200)


@app.route(f"{PREFIX}/seasons/<sid>/close-renewal", methods=["POST"])
def season_close_renewal(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    season = get_season(sid)
    if season["status"] != "RENEWAL_OPEN":
        raise err(errors.ERR_INVALID_STATE)
    if clock() < parse_iso(season["renewal_window_closes_at"]):
        raise err(errors.ERR_RENEWAL_WINDOW_NOT_OPEN)
    # Cascade: RENEWAL_OFFERED seats on this season's subscriptions -> RELEASED;
    # released_seat_count += 1 per release.
    released = 0
    for ss in store.subscription_seats.values():
        sub = store.subscriptions.get(ss["subscription_id"])
        if sub is None or sub["season_id"] != season["id"]:
            continue
        if ss["status"] == "RENEWAL_OFFERED":
            ss["status"] = "RELEASED"
            store.touch(ss)
            released += 1
    season["released_seat_count"] = season.get("released_seat_count", 0) + released
    season["status"] = "ON_SALE"
    store.touch(season)
    return success(view(season), status=200)


@app.route(f"{PREFIX}/seasons/<sid>/close", methods=["POST"])
def season_close(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    season = get_season(sid)
    if season["status"] != "ON_SALE":
        raise err(errors.ERR_INVALID_STATE)
    # Precondition: every Performance under this season's productions is SETTLED
    # or CANCELLED.
    prod_ids = {p["id"] for p in store.productions.values()
                if p["season_id"] == season["id"]}
    for perf in store.performances.values():
        if perf["production_id"] in prod_ids and perf["status"] not in ("SETTLED", "CANCELLED"):
            raise err(errors.ERR_INVALID_STATE)
    season["status"] = "CLOSED"
    store.touch(season)
    return success(view(season), status=200)


# ===========================================================================
# Productions — PRD §3.1
# ===========================================================================
@app.route(f"{PREFIX}/productions", methods=["POST"])
def create_production():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "ArtisticDirector"})
    body = svc.body_or_400()
    season_id = svc.req_str(body, "season_id")
    title = svc.req_str(body, "title")
    accessibility = body.get("accessibility_offered", [])
    if accessibility is None:
        accessibility = []
    if not isinstance(accessibility, list) or any(
        (not isinstance(a, str) or a not in ACCESS_OFFERED) for a in accessibility
    ):
        raise err(errors.ERR_VALIDATION,
                  "accessibility_offered must be a list of ASL/AUDIO_DESCRIPTION/OPEN_CAPTION")
    get_season(season_id)
    obj = {
        "id": store.new_id(),
        "season_id": season_id,
        "title": title,
        "accessibility_offered": list(accessibility),
        "status": "DRAFT",
    }
    store.stamp_new(obj)
    store.productions[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/productions/<pid>", methods=["GET"])
def get_one_production(pid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    obj = get_production(pid)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/productions", methods=["GET"])
def list_productions():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    season_id = request.args.get("season_id")
    items = [p for p in store.productions.values()
             if season_id is None or p["season_id"] == season_id]
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/productions/<pid>/announce", methods=["POST"])
def production_announce(pid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "ArtisticDirector"})
    prod = get_production(pid)
    if prod["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE)
    prod["status"] = "ANNOUNCED"
    store.touch(prod)
    return success(view(prod), status=200)


# ===========================================================================
# Venues & Seats — PRD §3.1
# ===========================================================================
@app.route(f"{PREFIX}/venues", methods=["POST"])
def create_venue():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    body = svc.body_or_400()
    name = svc.req_str(body, "name")
    obj = {
        "id": store.new_id(),
        "name": name,
        "total_seat_count": 0,
    }
    store.stamp_new(obj)
    store.venues[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/venues/<vid>", methods=["GET"])
def get_one_venue(vid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    obj = get_venue(vid)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/seats", methods=["POST"])
def create_seat():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    body = svc.body_or_400()
    venue_id = svc.req_str(body, "venue_id")
    section = svc.req_str(body, "section")
    row_label = svc.req_str(body, "row_label")
    seat_number = svc.req_int(body, "seat_number", min_value=1)
    price_tier = svc.req_enum(body, "price_tier", PRICE_TIERS)
    is_accessible = svc.opt_bool(body, "is_accessible", default=False)
    venue = get_venue(venue_id)
    obj = {
        "id": store.new_id(),
        "venue_id": venue_id,
        "section": section,
        "row_label": row_label,
        "seat_number": seat_number,
        "price_tier": price_tier,
        "is_accessible": is_accessible,
        "naming_status": "UNNAMED",
        "named_plaque_text": None,
    }
    store.stamp_new(obj)
    store.seats[obj["id"]] = obj
    venue["total_seat_count"] = venue.get("total_seat_count", 0) + 1
    store.touch(venue)
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/seats/<sid>", methods=["GET"])
def get_one_seat(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    obj = get_seat(sid)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/seats", methods=["GET"])
def list_seats():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    venue_id = request.args.get("venue_id")
    items = [s for s in store.seats.values()
             if venue_id is None or s["venue_id"] == venue_id]
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


# ===========================================================================
# Performances — PRD §3.2
# ===========================================================================
@app.route(f"{PREFIX}/performances", methods=["POST"])
def create_performance():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    body = svc.body_or_400()
    production_id = svc.req_str(body, "production_id")
    venue_id = svc.req_str(body, "venue_id")
    starts_at = svc.req_iso(body, "starts_at")
    on_sale_at = svc.req_iso(body, "on_sale_at")
    will_call = svc.opt_int(body, "will_call_cutoff_minutes", default=30, min_value=0)
    demand = svc.opt_number(body, "demand_multiplier", default=1.0,
                            min_value=0.5, max_value=3.0)
    get_production(production_id)
    get_venue(venue_id)
    obj = {
        "id": store.new_id(),
        "production_id": production_id,
        "venue_id": venue_id,
        "starts_at": starts_at,
        "on_sale_at": on_sale_at,
        "will_call_cutoff_minutes": will_call,
        "status": "DRAFT",
        "demand_multiplier": demand,
        "capacity": None,
        "held_seat_count": 0,
        "sold_seat_count": 0,
        "available_seat_count": None,
        "gross_sales_cents": 0,
    }
    store.stamp_new(obj)
    store.performances[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/performances/<pid>", methods=["GET"])
def get_one_performance(pid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    obj = get_performance(pid)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/performances", methods=["GET"])
def list_performances():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"})
    production_id = request.args.get("production_id")
    venue_id = request.args.get("venue_id")
    items = [p for p in store.performances.values()
             if (production_id is None or p["production_id"] == production_id)
             and (venue_id is None or p["venue_id"] == venue_id)]
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/performances/<pid>/schedule", methods=["POST"])
def performance_schedule(pid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    perf = get_performance(pid)
    if perf["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE)
    production = store.productions[perf["production_id"]]
    seats_in_venue = [s for s in store.seats.values() if s["venue_id"] == perf["venue_id"]]
    if production["status"] != "ANNOUNCED" or len(seats_in_venue) < 1:
        raise err(errors.ERR_INVALID_STATE)
    perf["capacity"] = len(seats_in_venue)
    perf["status"] = "SCHEDULED"
    svc.recompute_inventory(perf)
    perf["available_seat_count"] = perf["capacity"]
    store.touch(perf)
    return success(view(perf), status=200)


@app.route(f"{PREFIX}/performances/<pid>/open-sales", methods=["POST"])
def performance_open_sales(pid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    perf = get_performance(pid)
    if perf["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE)
    if clock() < parse_iso(perf["on_sale_at"]):
        raise err(errors.ERR_PERFORMANCE_NOT_ON_SALE)
    perf["status"] = "ON_SALE"
    store.touch(perf)
    return success(view(perf), status=200)


@app.route(f"{PREFIX}/performances/<pid>/suspend-sales", methods=["POST"])
def performance_suspend_sales(pid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    perf = get_performance(pid)
    if perf["status"] != "ON_SALE":
        raise err(errors.ERR_INVALID_STATE)
    perf["status"] = "SCHEDULED"
    store.touch(perf)
    return success(view(perf), status=200)


@app.route(f"{PREFIX}/performances/<pid>/settle", methods=["POST"])
def performance_settle(pid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    perf = get_performance(pid)
    if perf["status"] != "ON_SALE":
        raise err(errors.ERR_INVALID_STATE)
    if clock() < parse_iso(perf["starts_at"]):
        raise err(errors.ERR_SETTLE_BEFORE_CURTAIN)
    # Cascade remaining HELD unpaid tickets -> VOID, then compute gross_sales.
    for t in store.tickets.values():
        if t["performance_id"] != perf["id"]:
            continue
        if t["fulfillment_status"] == "HELD" and t["payment_status"] == "UNPAID":
            t["fulfillment_status"] = "VOID"
            store.touch(t)
    perf["status"] = "SETTLED"
    svc.recompute_inventory(perf)
    store.touch(perf)
    return success(view(perf), status=200)


@app.route(f"{PREFIX}/performances/<pid>/cancel", methods=["POST"])
def performance_cancel(pid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin"})
    perf = get_performance(pid)
    if perf["status"] not in ("DRAFT", "SCHEDULED", "ON_SALE"):
        raise err(errors.ERR_INVALID_STATE)
    # Depth-3 cascade (PRD §3.2): every non-VOID ticket -> VOID; each PAID such
    # ticket -> REFUNDED crediting patron by price_cents; each SUBSCRIPTION-origin
    # voided ticket releases its SubscriptionSeat.
    for t in store.tickets.values():
        if t["performance_id"] != perf["id"]:
            continue
        if t["fulfillment_status"] == "VOID":
            continue
        was_paid = t["payment_status"] == "PAID"
        t["fulfillment_status"] = "VOID"
        if was_paid:
            t["payment_status"] = "REFUNDED"
            patron = store.patrons.get(t["patron_id"])
            if patron is not None:
                patron["account_credit_cents"] = max(
                    0, patron.get("account_credit_cents", 0) + t["price_cents"])
                store.touch(patron)
        if t["origin"] == "SUBSCRIPTION" and t.get("subscription_id"):
            # Release the subscription seat backing this ticket (matched by seat
            # within the same subscription).
            for ss in store.subscription_seats.values():
                if ss["subscription_id"] == t["subscription_id"] and ss["seat_id"] == t["seat_id"]:
                    if ss["status"] != "RELEASED":
                        ss["status"] = "RELEASED"
                        store.touch(ss)
        store.touch(t)
    perf["status"] = "CANCELLED"
    svc.recompute_inventory(perf)
    store.touch(perf)
    return success(view(perf), status=200)


# ===========================================================================
# Patrons — PRD §3.3
# ===========================================================================
@app.route(f"{PREFIX}/patrons", methods=["POST"])
def create_patron():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent"})
    body = svc.body_or_400()
    email = svc.req_str(body, "email")
    full_name = svc.req_str(body, "full_name")
    if any(p["email"] == email for p in store.patrons.values()):
        raise err(errors.ERR_VALIDATION, "email must be unique among patrons")
    obj = {
        "id": store.new_id(),
        "email": email,
        "full_name": full_name,
        "donor_level": "NONE",
        "lifetime_donation_cents": 0,
        "account_credit_cents": 0,
    }
    store.stamp_new(obj)
    store.patrons[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/patrons/<pid>", methods=["GET"])
def get_one_patron(pid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    obj = get_patron(pid)
    check_patron_owns(role, user_id, obj["id"])
    return success(view(obj), status=200)


# ===========================================================================
# Subscriptions — PRD §3.3, §3.4
# ===========================================================================
@app.route(f"{PREFIX}/subscriptions", methods=["POST"])
def create_subscription():
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    body = svc.body_or_400()
    season_id = svc.req_str(body, "season_id")
    patron_id = svc.req_str(body, "patron_id")
    prior_id = svc.opt_str(body, "prior_subscription_id", default=None)
    check_patron_owns(role, user_id, patron_id)
    get_season(season_id)
    get_patron(patron_id)
    if prior_id is not None:
        get_subscription(prior_id)
    obj = {
        "id": store.new_id(),
        "season_id": season_id,
        "patron_id": patron_id,
        "prior_subscription_id": prior_id,
        "status": "DRAFT",
        "is_renewal": prior_id is not None,
        "seat_count": 0,
        "total_price_cents": 0,
    }
    store.stamp_new(obj)
    store.subscriptions[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/subscriptions/<sid>", methods=["GET"])
def get_one_subscription(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    obj = get_subscription(sid)
    check_patron_owns(role, user_id, obj["patron_id"])
    refresh_seat_count(obj)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/subscriptions", methods=["GET"])
def list_subscriptions():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    season_id = request.args.get("season_id")
    patron_id = request.args.get("patron_id")
    prior_id = request.args.get("prior_subscription_id")
    items = []
    for s in store.subscriptions.values():
        if season_id is not None and s["season_id"] != season_id:
            continue
        if patron_id is not None and s["patron_id"] != patron_id:
            continue
        if prior_id is not None and s.get("prior_subscription_id") != prior_id:
            continue
        if role == "Patron" and s["patron_id"] != user_id:
            continue
        refresh_seat_count(s)
        items.append(s)
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


def refresh_seat_count(sub):
    sub["seat_count"] = sum(
        1 for ss in store.subscription_seats.values()
        if ss["subscription_id"] == sub["id"] and ss["status"] == "ASSIGNED"
    )


@app.route(f"{PREFIX}/subscription-seats", methods=["POST"])
def create_subscription_seat():
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    body = svc.body_or_400()
    subscription_id = svc.req_str(body, "subscription_id")
    seat_id = svc.req_str(body, "seat_id")
    sub = get_subscription(subscription_id)
    seat = get_seat(seat_id)
    check_patron_owns(role, user_id, sub["patron_id"])
    # A seat is renewable/assignable unless it is already ASSIGNED on another
    # subscription in this season (true double-booking). A RENEWAL_OFFERED seat is
    # a renewal reservation for the prior holder and may be carried into the
    # successor subscription, so it does NOT block assignment (PRD §3.3/§3.4).
    for ss in store.subscription_seats.values():
        if ss["seat_id"] != seat_id or ss["subscription_id"] == subscription_id:
            continue
        other = store.subscriptions.get(ss["subscription_id"])
        if other is None or other["season_id"] != sub["season_id"]:
            continue
        if ss["status"] == "ASSIGNED":
            raise err(errors.ERR_SEAT_NOT_RENEWABLE)
    obj = {
        "id": store.new_id(),
        "subscription_id": subscription_id,
        "seat_id": seat_id,
        "status": "ASSIGNED",
        "per_seat_price_cents": None,
    }
    store.stamp_new(obj)
    store.subscription_seats[obj["id"]] = obj
    refresh_seat_count(sub)
    store.touch(sub)
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/subscription-seats/<sid>", methods=["GET"])
def get_one_subscription_seat(sid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    obj = store.subscription_seats.get(sid)
    if obj is None:
        raise err(errors.ERR_SEAT_NOT_FOUND)
    if role == "Patron":
        sub = store.subscriptions.get(obj["subscription_id"])
        check_patron_owns(role, user_id, sub["patron_id"] if sub else None)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/subscription-seats", methods=["GET"])
def list_subscription_seats():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    subscription_id = request.args.get("subscription_id")
    seat_id = request.args.get("seat_id")
    items = []
    for ss in store.subscription_seats.values():
        if subscription_id is not None and ss["subscription_id"] != subscription_id:
            continue
        if seat_id is not None and ss["seat_id"] != seat_id:
            continue
        if role == "Patron":
            sub = store.subscriptions.get(ss["subscription_id"])
            if sub is None or sub["patron_id"] != user_id:
                continue
        items.append(ss)
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/subscriptions/<sid>/activate", methods=["POST"])
def subscription_activate(sid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    body = svc.body_or_400()
    expected_season_version = svc.req_int(body, "expected_season_version")
    sub = get_subscription(sid)
    if sub["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE)
    assigned = [ss for ss in store.subscription_seats.values()
                if ss["subscription_id"] == sub["id"] and ss["status"] == "ASSIGNED"]
    if len(assigned) < 1:
        raise err(errors.ERR_INVALID_STATE)
    season = store.seasons[sub["season_id"]]
    # OCC (priority 9): expected_season_version must equal Season.version.
    if expected_season_version != season["version"]:
        raise err(errors.ERR_STALE_SEASON_VERSION)
    svc.price_subscription(sub)
    sub["status"] = "ACTIVE"
    refresh_seat_count(sub)
    store.touch(sub)
    # Increment Season.version by one.
    store.touch(season)
    return success(view(sub), status=200)


@app.route(f"{PREFIX}/subscriptions/<sid>/offer-renewal", methods=["POST"])
def subscription_offer_renewal(sid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    sub = get_subscription(sid)
    if sub["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE)
    season = store.seasons[sub["season_id"]]
    if season["status"] != "RENEWAL_OPEN":
        raise err(errors.ERR_INVALID_STATE)
    sub["status"] = "RENEWAL_PENDING"
    store.touch(sub)
    return success(view(sub), status=200)


@app.route(f"{PREFIX}/subscriptions/<sid>/confirm-renewal", methods=["POST"])
def subscription_confirm_renewal(sid):
    user_id, role = get_context()
    require_role(role, {"Patron"})
    sub = get_subscription(sid)
    check_patron_owns(role, user_id, sub["patron_id"])
    if sub["status"] != "RENEWAL_PENDING":
        raise err(errors.ERR_INVALID_STATE)
    # Precondition: a successor subscription (prior_subscription_id == sid) in
    # ACTIVE exists.
    successor = None
    for s in store.subscriptions.values():
        if s.get("prior_subscription_id") == sub["id"] and s["status"] == "ACTIVE":
            successor = s
            break
    if successor is None:
        raise err(errors.ERR_INVALID_STATE)
    # Cascade: successor RENEWAL_OFFERED seats -> ASSIGNED; reprice successor with
    # loyalty discount.
    for ss in store.subscription_seats.values():
        if ss["subscription_id"] == successor["id"] and ss["status"] == "RENEWAL_OFFERED":
            ss["status"] = "ASSIGNED"
            store.touch(ss)
    svc.price_subscription(successor)
    refresh_seat_count(successor)
    store.touch(successor)
    sub["status"] = "RENEWED"
    store.touch(sub)
    return success(view(sub), status=200)


@app.route(f"{PREFIX}/subscriptions/<sid>/cancel", methods=["POST"])
def subscription_cancel(sid):
    user_id, role = get_context()
    require_role(role, {"Patron"})
    sub = get_subscription(sid)
    check_patron_owns(role, user_id, sub["patron_id"])
    if sub["status"] not in ("DRAFT", "ACTIVE", "RENEWAL_PENDING"):
        raise err(errors.ERR_INVALID_STATE)
    # Cascade: ASSIGNED/RENEWAL_OFFERED seats -> RELEASED; credit patron by
    # total_price_cents.
    for ss in store.subscription_seats.values():
        if ss["subscription_id"] == sub["id"] and ss["status"] in ("ASSIGNED", "RENEWAL_OFFERED"):
            ss["status"] = "RELEASED"
            store.touch(ss)
    patron = store.patrons.get(sub["patron_id"])
    if patron is not None:
        patron["account_credit_cents"] = max(
            0, patron.get("account_credit_cents", 0) + sub.get("total_price_cents", 0))
        store.touch(patron)
    sub["status"] = "CANCELLED"
    refresh_seat_count(sub)
    store.touch(sub)
    return success(view(sub), status=200)


# ===========================================================================
# Tickets — PRD §3.5
# ===========================================================================
@app.route(f"{PREFIX}/tickets", methods=["POST"])
def create_ticket():
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    body = svc.body_or_400()
    performance_id = svc.req_str(body, "performance_id")
    seat_id = svc.req_str(body, "seat_id")
    patron_id = svc.req_str(body, "patron_id")
    origin = svc.req_enum(body, "origin", TICKET_ORIGINS)
    expected_perf_version = svc.req_int(body, "expected_performance_version")
    subscription_id = svc.opt_str(body, "subscription_id", default=None)
    accessibility_service = svc.opt_enum(body, "accessibility_service",
                                         ACCESS_SERVICES, default="NONE")
    # Ownership (priority 2): patron acting on own ticket.
    check_patron_owns(role, user_id, patron_id)
    # Existence (priority 3), left-to-right: performance, seat, patron, subscription.
    perf = get_performance(performance_id)
    seat = get_seat(seat_id)
    patron = get_patron(patron_id)
    if subscription_id is not None:
        get_subscription(subscription_id)
    # State (priority 4) + temporal (priority 5): single hold requires ON_SALE.
    if perf["status"] != "ON_SALE":
        raise err(errors.ERR_PERFORMANCE_NOT_ON_SALE)
    # Seat/accessibility constraints (priority 6).
    if seat["venue_id"] != perf["venue_id"]:
        raise err(errors.ERR_SEAT_NOT_IN_VENUE)
    for t in store.tickets.values():
        if t["performance_id"] == perf["id"] and t["seat_id"] == seat_id \
                and t["fulfillment_status"] != "VOID":
            raise err(errors.ERR_SEAT_ALREADY_TAKEN)
    if accessibility_service != "NONE":
        production = store.productions[perf["production_id"]]
        if accessibility_service not in production.get("accessibility_offered", []):
            raise err(errors.ERR_ACCESSIBILITY_UNAVAILABLE)
    # Fiscal capacity (priority 8): may not exceed available_seat_count.
    if perf.get("available_seat_count") is not None and perf["available_seat_count"] <= 0:
        raise err(errors.ERR_PERFORMANCE_SOLD_OUT)
    # OCC (priority 9): expected_performance_version must equal Performance.version.
    if expected_perf_version != perf["version"]:
        raise err(errors.ERR_STALE_PERFORMANCE_VERSION)
    # Pricing.
    if origin == "SINGLE":
        price = svc.single_ticket_price(seat, perf, patron)
    else:  # SUBSCRIPTION: copy per_seat_price_cents from owning subscription seat.
        price = 0
        if subscription_id is not None:
            for ss in store.subscription_seats.values():
                if ss["subscription_id"] == subscription_id and ss["seat_id"] == seat_id:
                    price = ss.get("per_seat_price_cents") or 0
                    break
    hold_expires = (clock() + timedelta(minutes=svc.HOLD_TTL_MINUTES))
    hold_expires_iso = hold_expires.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{hold_expires.microsecond // 1000:03d}Z"
    obj = {
        "id": store.new_id(),
        "performance_id": performance_id,
        "seat_id": seat_id,
        "patron_id": patron_id,
        "subscription_id": subscription_id,
        "origin": origin,
        "payment_status": "UNPAID",
        "fulfillment_status": "HELD",
        "price_cents": price,
        "hold_expires_at": hold_expires_iso,
        "accessibility_service": accessibility_service,
    }
    store.stamp_new(obj)
    store.tickets[obj["id"]] = obj
    # Increment Performance.version by one; recompute inventory.
    store.touch(perf)
    svc.recompute_inventory(perf)
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/tickets/<tid>", methods=["GET"])
def get_one_ticket(tid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    obj = get_ticket(tid)
    check_patron_owns(role, user_id, obj["patron_id"])
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/tickets", methods=["GET"])
def list_tickets():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    performance_id = request.args.get("performance_id")
    seat_id = request.args.get("seat_id")
    patron_id = request.args.get("patron_id")
    subscription_id = request.args.get("subscription_id")
    items = []
    for t in store.tickets.values():
        if performance_id is not None and t["performance_id"] != performance_id:
            continue
        if seat_id is not None and t["seat_id"] != seat_id:
            continue
        if patron_id is not None and t["patron_id"] != patron_id:
            continue
        if subscription_id is not None and t.get("subscription_id") != subscription_id:
            continue
        if role == "Patron" and t["patron_id"] != user_id:
            continue
        items.append(t)
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/tickets/<tid>/pay", methods=["POST"])
def ticket_pay(tid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    ticket = get_ticket(tid)
    check_patron_owns(role, user_id, ticket["patron_id"])
    # State (priority 4): HELD->ISSUED only when payment_status UNPAID.
    if ticket["fulfillment_status"] != "HELD" or ticket["payment_status"] != "UNPAID":
        raise err(errors.ERR_INVALID_STATE)
    perf = store.performances.get(ticket["performance_id"])
    # Temporal (priority 5): performance must be ON_SALE.
    if perf is None or perf["status"] != "ON_SALE":
        raise err(errors.ERR_PERFORMANCE_NOT_ON_SALE)
    ticket["payment_status"] = "PAID"
    ticket["fulfillment_status"] = "ISSUED"
    store.touch(ticket)
    svc.recompute_inventory(perf)
    store.touch(perf)
    return success(view(ticket), status=200)


@app.route(f"{PREFIX}/tickets/<tid>/will-call-pickup", methods=["POST"])
def ticket_will_call(tid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    ticket = get_ticket(tid)
    if ticket["fulfillment_status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE)
    if ticket["payment_status"] != "PAID":
        raise err(errors.ERR_INVALID_STATE)
    perf = store.performances[ticket["performance_id"]]
    cutoff_instant = parse_iso(perf["starts_at"]) - timedelta(
        minutes=perf["will_call_cutoff_minutes"])
    # Permitted only while clock is strictly earlier than (curtain - cutoff).
    if not (clock() < cutoff_instant):
        raise err(errors.ERR_WILL_CALL_CLOSED)
    ticket["fulfillment_status"] = "COLLECTED"
    store.touch(ticket)
    svc.recompute_inventory(perf)
    return success(view(ticket), status=200)


@app.route(f"{PREFIX}/tickets/<tid>/release", methods=["POST"])
def ticket_release(tid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    ticket = get_ticket(tid)
    check_patron_owns(role, user_id, ticket["patron_id"])
    if ticket["fulfillment_status"] != "HELD" or ticket["payment_status"] != "UNPAID":
        raise err(errors.ERR_INVALID_STATE)
    ticket["fulfillment_status"] = "VOID"
    store.touch(ticket)
    perf = store.performances.get(ticket["performance_id"])
    if perf is not None:
        svc.recompute_inventory(perf)
        store.touch(perf)
    return success(view(ticket), status=200)


# ===========================================================================
# Donations — PRD §3.6
# ===========================================================================
@app.route(f"{PREFIX}/donations", methods=["POST"])
def create_donation():
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    body = svc.body_or_400()
    patron_id = svc.req_str(body, "patron_id")
    amount_cents = svc.req_int(body, "amount_cents", min_value=1)
    seat_id = svc.opt_str(body, "seat_id", default=None)
    plaque_text = svc.opt_str(body, "plaque_text", default=None)
    check_patron_owns(role, user_id, patron_id)
    get_patron(patron_id)
    if seat_id is not None:
        get_seat(seat_id)
    obj = {
        "id": store.new_id(),
        "patron_id": patron_id,
        "seat_id": seat_id,
        "amount_cents": amount_cents,
        "plaque_text": plaque_text,
        "status": "PLEDGED",
    }
    store.stamp_new(obj)
    store.donations[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/donations/<did>", methods=["GET"])
def get_one_donation(did):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    obj = get_donation(did)
    check_patron_owns(role, user_id, obj["patron_id"])
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/donations", methods=["GET"])
def list_donations():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    patron_id = request.args.get("patron_id")
    seat_id = request.args.get("seat_id")
    items = []
    for d in store.donations.values():
        if patron_id is not None and d["patron_id"] != patron_id:
            continue
        if seat_id is not None and d.get("seat_id") != seat_id:
            continue
        if role == "Patron" and d["patron_id"] != user_id:
            continue
        items.append(d)
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/donations/<did>/fulfill", methods=["POST"])
def donation_fulfill(did):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    don = get_donation(did)
    if don["status"] != "PLEDGED":
        raise err(errors.ERR_INVALID_STATE)
    # Referential (priority 7): seat-naming requires seat UNNAMED.
    if don.get("seat_id") is not None:
        seat = store.seats[don["seat_id"]]
        if seat["naming_status"] != "UNNAMED":
            raise err(errors.ERR_SEAT_ALREADY_NAMED)
    don["status"] = "FULFILLED"
    store.touch(don)
    if don.get("seat_id") is not None:
        seat = store.seats[don["seat_id"]]
        seat["naming_status"] = "NAMED"
        seat["named_plaque_text"] = don.get("plaque_text")
        store.touch(seat)
    patron = store.patrons.get(don["patron_id"])
    if patron is not None:
        svc.recompute_donor(patron)
        store.touch(patron)
    return success(view(don), status=200)


@app.route(f"{PREFIX}/donations/<did>/refund", methods=["POST"])
def donation_refund(did):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    don = get_donation(did)
    if don["status"] != "FULFILLED":
        raise err(errors.ERR_INVALID_STATE)
    don["status"] = "REFUNDED"
    store.touch(don)
    patron = store.patrons.get(don["patron_id"])
    if patron is not None:
        svc.recompute_donor(patron)  # removes this gift from lifetime; may demote
        store.touch(patron)
    return success(view(don), status=200)


# ===========================================================================
# Exchanges / Flex-pass — PRD §3.7
# ===========================================================================
@app.route(f"{PREFIX}/exchanges", methods=["POST"])
def create_exchange():
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent", "Patron"})
    body = svc.body_or_400()
    original_ticket_id = svc.req_str(body, "original_ticket_id")
    target_performance_id = svc.req_str(body, "target_performance_id")
    target_seat_id = svc.req_str(body, "target_seat_id")
    mode = svc.req_enum(body, "mode", EXCHANGE_MODES)
    # Existence, left-to-right.
    original = get_ticket(original_ticket_id)
    get_performance(target_performance_id)
    get_seat(target_seat_id)
    check_patron_owns(role, user_id, original["patron_id"])
    obj = {
        "id": store.new_id(),
        "original_ticket_id": original_ticket_id,
        "target_performance_id": target_performance_id,
        "target_seat_id": target_seat_id,
        "mode": mode,
        "status": "REQUESTED",
        "fee_cents": None,
        "price_delta_cents": None,
        "new_ticket_id": None,
    }
    store.stamp_new(obj)
    store.exchanges[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/exchanges/<eid>", methods=["GET"])
def get_one_exchange(eid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    obj = get_exchange(eid)
    if role == "Patron":
        original = store.tickets.get(obj["original_ticket_id"])
        check_patron_owns(role, user_id, original["patron_id"] if original else None)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/exchanges", methods=["GET"])
def list_exchanges():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "BoxOfficeAgent", "Patron"})
    original_ticket_id = request.args.get("original_ticket_id")
    target_performance_id = request.args.get("target_performance_id")
    target_seat_id = request.args.get("target_seat_id")
    items = []
    for e in store.exchanges.values():
        if original_ticket_id is not None and e["original_ticket_id"] != original_ticket_id:
            continue
        if target_performance_id is not None and e["target_performance_id"] != target_performance_id:
            continue
        if target_seat_id is not None and e["target_seat_id"] != target_seat_id:
            continue
        if role == "Patron":
            original = store.tickets.get(e["original_ticket_id"])
            if original is None or original["patron_id"] != user_id:
                continue
        items.append(e)
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/exchanges/<eid>/complete", methods=["POST"])
def exchange_complete(eid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    body = svc.body_or_400()
    pay_from_credit = svc.opt_bool(body, "pay_from_credit", default=False)
    exch = get_exchange(eid)
    if exch["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE)
    original = store.tickets[exch["original_ticket_id"]]
    target_perf = store.performances[exch["target_performance_id"]]
    target_seat = store.seats[exch["target_seat_id"]]
    # Original must be ISSUED + PAID.
    if original["fulfillment_status"] != "ISSUED" or original["payment_status"] != "PAID":
        raise err(errors.ERR_INVALID_STATE)
    # Referential (priority 7): target seat must be in target performance's venue.
    if target_seat["venue_id"] != target_perf["venue_id"]:
        raise err(errors.ERR_TARGET_SEAT_MISMATCH)
    # Seat constraint (priority 6 semantics): target seat free of non-VOID ticket.
    for t in store.tickets.values():
        if t["performance_id"] == target_perf["id"] and t["seat_id"] == target_seat["id"] \
                and t["fulfillment_status"] != "VOID":
            raise err(errors.ERR_SEAT_ALREADY_TAKEN)
    patron = store.patrons[original["patron_id"]]
    target_single_price = svc.single_ticket_price(target_seat, target_perf, patron)
    fee, price_delta, total_charge = svc.exchange_fee(exch, original, target_single_price)
    # Fiscal (priority 8): pay_from_credit requires enough credit.
    if pay_from_credit and patron.get("account_credit_cents", 0) < total_charge:
        raise err(errors.ERR_INSUFFICIENT_CREDIT)
    # Mutate original.
    original["fulfillment_status"] = "EXCHANGED"
    original["payment_status"] = "REFUNDED"
    store.touch(original)
    # Mint replacement ISSUED/PAID ticket.
    hold = (clock() + timedelta(minutes=svc.HOLD_TTL_MINUTES))
    hold_iso = hold.strftime("%Y-%m-%dT%H:%M:%S.") + f"{hold.microsecond // 1000:03d}Z"
    new_ticket = {
        "id": store.new_id(),
        "performance_id": target_perf["id"],
        "seat_id": target_seat["id"],
        "patron_id": patron["id"],
        "subscription_id": None,
        "origin": "SINGLE",
        "payment_status": "PAID",
        "fulfillment_status": "ISSUED",
        "price_cents": target_single_price,
        "hold_expires_at": hold_iso,
        "accessibility_service": "NONE",
    }
    store.stamp_new(new_ticket)
    store.tickets[new_ticket["id"]] = new_ticket
    exch["fee_cents"] = fee
    exch["price_delta_cents"] = price_delta
    exch["new_ticket_id"] = new_ticket["id"]
    exch["status"] = "COMPLETED"
    store.touch(exch)
    if pay_from_credit:
        patron["account_credit_cents"] = max(
            0, patron.get("account_credit_cents", 0) - total_charge)
        store.touch(patron)
    # Recompute inventory on both affected performances.
    orig_perf = store.performances.get(original["performance_id"])
    if orig_perf is not None:
        svc.recompute_inventory(orig_perf)
        store.touch(orig_perf)
    svc.recompute_inventory(target_perf)
    store.touch(target_perf)
    return success(view(exch), status=200)


@app.route(f"{PREFIX}/exchanges/<eid>/deny", methods=["POST"])
def exchange_deny(eid):
    user_id, role = get_context()
    require_role(role, {"BoxOfficeAgent"})
    exch = get_exchange(eid)
    if exch["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE)
    exch["status"] = "DENIED"
    store.touch(exch)
    return success(view(exch), status=200)


# ===========================================================================
# Auditions & Casting — PRD §3.9
# ===========================================================================
@app.route(f"{PREFIX}/auditions", methods=["POST"])
def create_audition():
    user_id, role = get_context()
    require_role(role, {"ArtisticDirector"})
    body = svc.body_or_400()
    production_id = svc.req_str(body, "production_id")
    applicant_name = svc.req_str(body, "applicant_name")
    role_applied_for = svc.req_str(body, "role_applied_for")
    get_production(production_id)
    obj = {
        "id": store.new_id(),
        "production_id": production_id,
        "applicant_name": applicant_name,
        "role_applied_for": role_applied_for,
        "status": "SCHEDULED",
        "cast_role": None,
        "is_volunteer": False,
    }
    store.stamp_new(obj)
    store.auditions[obj["id"]] = obj
    return success(view(obj), status=201)


@app.route(f"{PREFIX}/auditions/<aid>", methods=["GET"])
def get_one_audition(aid):
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "ArtisticDirector"})
    obj = get_audition(aid)
    return success(view(obj), status=200)


@app.route(f"{PREFIX}/auditions", methods=["GET"])
def list_auditions():
    user_id, role = get_context()
    require_role(role, {"SeasonAdmin", "ArtisticDirector"})
    production_id = request.args.get("production_id")
    items = [a for a in store.auditions.values()
             if production_id is None or a["production_id"] == production_id]
    items = svc.sorted_by_created(items)
    window, pagination = svc.paginate(items)
    return success(view_list(window), status=200, pagination=pagination)


@app.route(f"{PREFIX}/auditions/<aid>/record", methods=["POST"])
def audition_record(aid):
    user_id, role = get_context()
    require_role(role, {"ArtisticDirector"})
    aud = get_audition(aid)
    if aud["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE)
    production = store.productions[aud["production_id"]]
    if production["status"] not in ("DRAFT", "ANNOUNCED"):
        raise err(errors.ERR_INVALID_STATE)
    aud["status"] = "AUDITIONED"
    store.touch(aud)
    return success(view(aud), status=200)


@app.route(f"{PREFIX}/auditions/<aid>/callback", methods=["POST"])
def audition_callback(aid):
    user_id, role = get_context()
    require_role(role, {"ArtisticDirector"})
    aud = get_audition(aid)
    if aud["status"] != "AUDITIONED":
        raise err(errors.ERR_INVALID_STATE)
    aud["status"] = "CALLBACK"
    store.touch(aud)
    return success(view(aud), status=200)


@app.route(f"{PREFIX}/auditions/<aid>/cast", methods=["POST"])
def audition_cast(aid):
    user_id, role = get_context()
    require_role(role, {"ArtisticDirector"})
    body = svc.body_or_400()
    cast_role = svc.req_str(body, "cast_role")
    is_volunteer = svc.opt_bool(body, "is_volunteer", default=False)
    aud = get_audition(aid)
    if aud["status"] not in ("AUDITIONED", "CALLBACK"):
        raise err(errors.ERR_INVALID_STATE)
    # Referential (priority 7): no existing CAST audition on this production holds
    # the same cast_role.
    for other in store.auditions.values():
        if other["production_id"] == aud["production_id"] and other["status"] == "CAST" \
                and other.get("cast_role") == cast_role:
            raise err(errors.ERR_ROLE_ALREADY_CAST)
    aud["status"] = "CAST"
    aud["cast_role"] = cast_role
    aud["is_volunteer"] = is_volunteer
    store.touch(aud)
    return success(view(aud), status=200)


@app.route(f"{PREFIX}/auditions/<aid>/decline", methods=["POST"])
def audition_decline(aid):
    user_id, role = get_context()
    require_role(role, {"ArtisticDirector"})
    aud = get_audition(aid)
    if aud["status"] not in ("SCHEDULED", "AUDITIONED", "CALLBACK"):
        raise err(errors.ERR_INVALID_STATE)
    aud["status"] = "DECLINED"
    store.touch(aud)
    return success(view(aud), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
