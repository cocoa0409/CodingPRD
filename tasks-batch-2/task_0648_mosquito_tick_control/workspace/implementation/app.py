"""Mosquito & Tick Control API — Flask entry point.

In-memory only. The store starts empty on every boot; no entity is seeded.
start.sh re-invokes this before every per-test reboot, wiping all state.
"""
import os
from datetime import timedelta

from flask import Flask, request

from clock import clock
from db import db
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
    ERR_NO_QUALIFYING_WEATHER, ERR_RESCHEDULE_LIMIT, ERR_DATE_OUT_OF_SEASON,
    ERR_GUARANTEE_EXPIRED, ERR_ZONE_NOT_TREATABLE, ERR_REGION_MISMATCH,
    ERR_ROUTE_AT_CAPACITY, ERR_RETREAT_ALREADY_EXISTS, ERR_UNDERPAYMENT,
    ERR_NO_APPLICATION_LOGGED, ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_ROUTE_NOT_EMPTY,
)
from middleware import get_identity, require_role
from response import success, list_success, error_body
from serialize import (
    plain, property_view, subscription_view, crew_route_view,
)
from helpers import (
    require_body, optional_body, parse_pagination, parse_date, parse_iso,
    req_str, opt_str, req_int, opt_int, req_number, opt_bool, req_enum, req_date,
)
import services as S

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_body(ERR_NOT_FOUND, "Resource not found."), 404


@app.errorhandler(405)
def handle_405(e):
    return error_body(ERR_NOT_FOUND, "Method not allowed."), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_body(ERR_INVALID_REQUEST, "Unexpected error: %s" % str(e)), 422


# ---------------------------------------------------------------------------
# Lookup helpers (existence checks -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def must_get(store, _id):
    obj = store.get(_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "Referenced resource does not exist.")
    return obj


# ---------------------------------------------------------------------------
# Ownership helpers (PRD §2.1, validation priority 4)
# ---------------------------------------------------------------------------
def property_owner_id(prop):
    return prop["account_holder_id"]


def subscription_owner_id(sub):
    prop = db.properties.get(sub["property_id"])
    return prop["account_holder_id"] if prop else None


def visit_owner_id(visit):
    sub = db.subscriptions.get(visit["subscription_id"])
    return subscription_owner_id(sub) if sub else None


def invoice_owner_id(inv):
    sub = db.subscriptions.get(inv["subscription_id"])
    return subscription_owner_id(sub) if sub else None


def assert_account_holder_owns(role, uid, owner_id):
    """An AccountHolder who targets a resource that does not roll up to their
    own X-User-ID is rejected with ERR_NOT_RESOURCE_OWNER (PRD §2.1)."""
    if role == "AccountHolder" and uid != owner_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting account holder does not own this resource.")


def crew_owns_visit_route(role, uid, visit):
    """A CrewTech may act only on a visit whose route's Crew.id == X-User-ID
    (PRD §2.1)."""
    if role != "CrewTech":
        return
    route = db.crew_routes.get(visit["crew_route_id"]) if visit["crew_route_id"] else None
    crew_id = route["crew_id"] if route else None
    if uid != crew_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting technician is not assigned to this visit's route.")


# ===========================================================================
# Bootstrap / config: ServicePlan
# ===========================================================================
@app.route("/service-plans", methods=["POST"])
def create_service_plan():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin"])
    body = require_body()
    tier = req_enum(body, "tier", {"BASIC", "PLUS", "PREMIER"})
    visit_interval_days = req_int(body, "visit_interval_days", minimum=14, maximum=28)
    per_visit_price = req_int(body, "per_visit_price_cents", minimum=0)
    seasonal_price = req_int(body, "seasonal_price_cents", minimum=0)
    includes_tick = opt_bool(body, "includes_tick_barrier", default=False)
    retreat_days = req_int(body, "retreat_guarantee_days", minimum=1, maximum=14)

    plan = {
        "tier": tier,
        "visit_interval_days": visit_interval_days,
        "per_visit_price_cents": per_visit_price,
        "seasonal_price_cents": seasonal_price,
        "includes_tick_barrier": includes_tick,
        "retreat_guarantee_days": retreat_days,
    }
    db.stamp_create_event(plan)
    db.service_plans[plan["id"]] = plan
    return success(plain(plan), status=201)


@app.route("/service-plans/<pid>", methods=["GET"])
def get_service_plan(pid):
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin", "Dispatcher"])
    plan = must_get(db.service_plans, pid)
    return success(plain(plan))


# ===========================================================================
# AccountHolder
# ===========================================================================
@app.route("/account-holders", methods=["POST"])
def create_account_holder():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "AccountHolder"])
    body = require_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    # email unique across AccountHolder.
    for h in db.account_holders.values():
        if h["email"] == email:
            raise err(ERR_INVALID_REQUEST, "Email already registered.")
    holder = {
        "email": email,
        "full_name": full_name,
        "wallet_credit_cents": 0,
    }
    db.stamp_create_full(holder)
    db.account_holders[holder["id"]] = holder
    return success(plain(holder), status=201)


@app.route("/account-holders/<hid>", methods=["GET"])
def get_account_holder(hid):
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    holder = must_get(db.account_holders, hid)
    return success(plain(holder))


@app.route("/account-holders/<hid>/properties", methods=["GET"])
def list_account_holder_properties(hid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    must_get(db.account_holders, hid)
    limit, offset = parse_pagination()
    items = [p for p in db.properties.values() if p["account_holder_id"] == hid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([property_view(p) for p in page], limit, offset, total)


# ===========================================================================
# Crew
# ===========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher"])
    body = require_body()
    tech_name = req_str(body, "tech_name")
    home_region = req_str(body, "home_region_code")
    daily_capacity = req_int(body, "daily_capacity", minimum=1, maximum=40)
    crew = {
        "tech_name": tech_name,
        "home_region_code": home_region,
        "daily_capacity": daily_capacity,
    }
    db.stamp_create_full(crew)
    db.crews[crew["id"]] = crew
    return success(plain(crew), status=201)


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher", "CrewTech"])
    crew = must_get(db.crews, cid)
    return success(plain(crew))


@app.route("/crews/<cid>/crew-routes", methods=["GET"])
def list_crew_routes_for_crew(cid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin", "CrewTech"])
    must_get(db.crews, cid)
    limit, offset = parse_pagination()
    items = [r for r in db.crew_routes.values() if r["crew_id"] == cid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([crew_route_view(r) for r in page], limit, offset, total)


# ===========================================================================
# Property + zones
# ===========================================================================
@app.route("/properties", methods=["POST"])
def create_property():
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    body = require_body()
    account_holder_id = req_str(body, "account_holder_id")
    street_address = req_str(body, "street_address")
    lot_size_sqft = req_int(body, "lot_size_sqft", minimum=1)
    service_region_code = req_str(body, "service_region_code")
    # Ownership: an AccountHolder may only create a property for themselves.
    assert_account_holder_owns(role, uid, account_holder_id)
    must_get(db.account_holders, account_holder_id)

    prop = {
        "account_holder_id": account_holder_id,
        "street_address": street_address,
        "lot_size_sqft": lot_size_sqft,
        "service_region_code": service_region_code,
    }
    db.stamp_create_full(prop)
    db.properties[prop["id"]] = prop
    return success(property_view(prop), status=201)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "Dispatcher", "BillingAdmin"])
    prop = must_get(db.properties, pid)
    assert_account_holder_owns(role, uid, property_owner_id(prop))
    return success(property_view(prop))


@app.route("/properties/<pid>/zones", methods=["POST"])
def create_zone(pid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    prop = must_get(db.properties, pid)
    assert_account_holder_owns(role, uid, property_owner_id(prop))
    body = require_body()
    label = req_str(body, "label")
    zone_type = req_enum(body, "zone_type", {"TURF", "PERIMETER", "WATER_FEATURE", "WOODLINE"})
    area_sqft = req_int(body, "area_sqft", minimum=1)

    zone = {
        "property_id": pid,
        "label": label,
        "zone_type": zone_type,
        "area_sqft": area_sqft,
        "status": "ACTIVE",
    }
    db.stamp_create_full(zone)
    db.treatment_zones[zone["id"]] = zone
    # Derived-field reconciliation: adding a zone mutates the property.
    db.touch(prop)
    return success(plain(zone), status=201)


@app.route("/properties/<pid>/zones", methods=["GET"])
def list_zones(pid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "Dispatcher", "CrewTech"])
    prop = must_get(db.properties, pid)
    assert_account_holder_owns(role, uid, property_owner_id(prop))
    limit, offset = parse_pagination()
    items = [z for z in db.treatment_zones.values() if z["property_id"] == pid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(z) for z in page], limit, offset, total)


@app.route("/zones/<zid>/exclude", methods=["POST"])
def exclude_zone(zid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    zone = must_get(db.treatment_zones, zid)
    prop = db.properties.get(zone["property_id"])
    assert_account_holder_owns(role, uid, property_owner_id(prop) if prop else None)
    # One-way ACTIVE -> EXCLUDED.
    if zone["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Zone is not ACTIVE.")
    zone["status"] = "EXCLUDED"
    db.touch(zone)
    # Derived-field reconciliation on the property (zone_count unchanged,
    # total_treatable_sqft drops this zone's area).
    if prop is not None:
        db.touch(prop)
    return success(plain(zone))


# ===========================================================================
# Subscription
# ===========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    body = require_body()
    property_id = req_str(body, "property_id")
    service_plan_id = req_str(body, "service_plan_id")
    billing_mode = req_enum(body, "billing_mode", {"PER_VISIT", "SEASONAL"})
    season_start_raw = req_str(body, "season_start_date")
    season_end_raw = req_str(body, "season_end_date")
    auto_renew = opt_bool(body, "auto_renew", default=True)

    # Existence (left-to-right): property then plan.
    prop = must_get(db.properties, property_id)
    assert_account_holder_owns(role, uid, property_owner_id(prop))
    must_get(db.service_plans, service_plan_id)

    # Body well-formedness: dates parseable; start <= end.
    start = parse_date(season_start_raw)
    end = parse_date(season_end_raw)
    if start > end:
        raise err(ERR_INVALID_REQUEST, "season_start_date must be on or before season_end_date.")

    sub = {
        "property_id": property_id,
        "service_plan_id": service_plan_id,
        "billing_mode": billing_mode,
        "season_start_date": season_start_raw,
        "season_end_date": season_end_raw,
        "status": "DRAFT",
        "auto_renew": auto_renew,
        "renewed_into_subscription_id": None,
    }
    db.stamp_create_full(sub)
    db.subscriptions[sub["id"]] = sub
    return success(subscription_view(sub), status=201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "Dispatcher", "BillingAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    return success(subscription_view(sub))


@app.route("/properties/<pid>/subscriptions", methods=["GET"])
def list_property_subscriptions(pid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "BillingAdmin"])
    prop = must_get(db.properties, pid)
    assert_account_holder_owns(role, uid, property_owner_id(prop))
    limit, offset = parse_pagination()
    items = [s for s in db.subscriptions.values() if s["property_id"] == pid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([subscription_view(s) for s in page], limit, offset, total)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "BillingAdmin"])
    limit, offset = parse_pagination()
    items = list(db.subscriptions.values())
    if "service_plan_id" in request.args:
        items = [s for s in items if s["service_plan_id"] == request.args.get("service_plan_id")]
    if "renewed_into_subscription_id" in request.args:
        want = request.args.get("renewed_into_subscription_id")
        items = [s for s in items if s["renewed_into_subscription_id"] == want]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([subscription_view(s) for s in page], limit, offset, total)


@app.route("/subscriptions/<sid>/activate", methods=["POST"])
def activate_subscription(sid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    # State precondition (priority 5).
    if sub["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Subscription is not DRAFT.")
    # Business preconditions: >=1 ACTIVE zone; season_start <= season_end.
    active_zones = [
        z for z in db.treatment_zones.values()
        if z["property_id"] == sub["property_id"] and z["status"] == "ACTIVE"
    ]
    if len(active_zones) < 1:
        raise err(ERR_INVALID_STATE, "Property has no ACTIVE treatment zone.")
    if parse_date(sub["season_start_date"]) > parse_date(sub["season_end_date"]):
        raise err(ERR_INVALID_STATE, "season_start_date must be on or before season_end_date.")
    plan = db.service_plans[sub["service_plan_id"]]
    S.activate_subscription(sub, plan)
    return success(subscription_view(sub))


@app.route("/subscriptions/<sid>/close-season", methods=["POST"])
def close_season(sid):
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin"])
    sub = must_get(db.subscriptions, sid)
    # State precondition.
    if sub["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Subscription is not ACTIVE.")
    if not (clock.today() > parse_date(sub["season_end_date"])):
        raise err(ERR_INVALID_STATE, "Logical current date is not past season_end_date.")
    for v in db.visits.values():
        if v["subscription_id"] == sid and v["status"] == "DISPATCHED":
            raise err(ERR_INVALID_STATE, "A visit is still DISPATCHED.")
    S.off_season_transition(sub)
    return success(subscription_view(sub))


@app.route("/subscriptions/<sid>/confirm-renewal", methods=["POST"])
def confirm_renewal(sid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    if sub["status"] != "OFF_SEASON":
        raise err(ERR_INVALID_STATE, "Subscription is not OFF_SEASON.")
    if sub["renewed_into_subscription_id"] is None:
        raise err(ERR_INVALID_STATE, "Subscription has no renewal successor.")
    successor = db.subscriptions.get(sub["renewed_into_subscription_id"])
    if successor is None or successor["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Renewal successor is not in DRAFT status.")
    # Activate the successor (DRAFT -> ACTIVE with its own recurring schedule).
    plan = db.service_plans[successor["service_plan_id"]]
    S.activate_subscription(successor, plan)
    sub["status"] = "RENEWED"
    db.touch(sub)
    return success(subscription_view(sub))


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    if sub["status"] == "DRAFT":
        sub["status"] = "CANCELLED"
        db.touch(sub)
        return success(subscription_view(sub))
    if sub["status"] == "ACTIVE":
        # Precondition: no visit currently DISPATCHED.
        for v in db.visits.values():
            if v["subscription_id"] == sid and v["status"] == "DISPATCHED":
                raise err(ERR_INVALID_STATE, "A visit is still DISPATCHED.")
        S.cancel_active_cascade(sub)
        return success(subscription_view(sub))
    raise err(ERR_INVALID_STATE, "Subscription cannot be cancelled from its current state.")


@app.route("/subscriptions/<sid>/special-event", methods=["POST"])
def schedule_special_event(sid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    body = require_body()
    scheduled_raw = req_str(body, "scheduled_date")
    # Specialized state-tier check (priority 18, same tier as priority 5).
    if sub["status"] != "ACTIVE":
        raise err(ERR_SUBSCRIPTION_NOT_ACTIVE, "Subscription is not ACTIVE.")
    scheduled = parse_date(scheduled_raw)
    # Date strictly after logical current date and on/before season_end_date.
    if not (scheduled > clock.today()):
        raise err(ERR_DATE_OUT_OF_SEASON, "scheduled_date must be strictly after the current date.")
    if scheduled > parse_date(sub["season_end_date"]):
        raise err(ERR_DATE_OUT_OF_SEASON, "scheduled_date must be on or before season_end_date.")

    visit = {
        "subscription_id": sid,
        "visit_kind": "SPECIAL_EVENT",
        "scheduled_date": scheduled_raw,
        "sequence_index": 0,
        "status": "SCHEDULED",
        "crew_route_id": None,
        "weather_event_id": None,
        "parent_visit_id": None,
        "reschedule_count": 0,
        "completed_at_date": None,
    }
    db.stamp_create_full(visit)
    db.visits[visit["id"]] = visit
    return success(plain(visit), status=201)


# ===========================================================================
# Visits
# ===========================================================================
def _visit_property(visit):
    sub = db.subscriptions.get(visit["subscription_id"])
    return db.properties.get(sub["property_id"]) if sub else None


@app.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "Dispatcher", "CrewTech", "BillingAdmin"])
    visit = must_get(db.visits, vid)
    assert_account_holder_owns(role, uid, visit_owner_id(visit))
    return success(plain(visit))


@app.route("/subscriptions/<sid>/visits", methods=["GET"])
def list_subscription_visits(sid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "Dispatcher", "BillingAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    limit, offset = parse_pagination()
    items = [v for v in db.visits.values() if v["subscription_id"] == sid]
    if "parent_visit_id" in request.args:
        items = [v for v in items if v["parent_visit_id"] == request.args.get("parent_visit_id")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(v) for v in page], limit, offset, total)


@app.route("/visits", methods=["GET"])
def list_visits():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher", "CrewTech"])
    limit, offset = parse_pagination()
    items = list(db.visits.values())
    if "crew_route_id" in request.args:
        items = [v for v in items if v["crew_route_id"] == request.args.get("crew_route_id")]
    if "weather_event_id" in request.args:
        items = [v for v in items if v["weather_event_id"] == request.args.get("weather_event_id")]
    if "parent_visit_id" in request.args:
        items = [v for v in items if v["parent_visit_id"] == request.args.get("parent_visit_id")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(v) for v in page], limit, offset, total)


@app.route("/visits/<vid>/weather-hold", methods=["POST"])
def weather_hold(vid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    body = require_body()
    weather_event_id = req_str(body, "weather_event_id")
    event = must_get(db.weather_events, weather_event_id)
    # State precondition (priority 5).
    if visit["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not SCHEDULED.")
    # Business safety (priority 8): a qualifying WeatherEvent must exist whose
    # region matches the property's region, event_date == scheduled_date, and
    # severity in {RAIN_HEAVY, WIND_HIGH}.
    prop = _visit_property(visit)
    region = prop["service_region_code"] if prop else None
    qualifies = False
    for ev in db.weather_events.values():
        if (ev["region_code"] == region
                and ev["event_date"] == visit["scheduled_date"]
                and ev["severity"] in S.QUALIFYING_SEVERITIES):
            qualifies = True
            break
    if not qualifies:
        raise err(ERR_NO_QUALIFYING_WEATHER, "No qualifying weather event for this visit's date/region.")
    # Reschedule cap (precondition reschedule_count < 3).
    if visit["reschedule_count"] >= S.RESCHEDULE_LIMIT:
        raise err(ERR_RESCHEDULE_LIMIT, "Visit has reached the reschedule limit.")
    # Record the matching event (the one supplied in the body, which must itself
    # qualify for this visit).
    if not (event["region_code"] == region
            and event["event_date"] == visit["scheduled_date"]
            and event["severity"] in S.QUALIFYING_SEVERITIES):
        raise err(ERR_NO_QUALIFYING_WEATHER, "Supplied weather event does not qualify for this visit.")
    visit["weather_event_id"] = weather_event_id
    visit["status"] = "WEATHER_HOLD"
    db.touch(visit)
    return success(plain(visit))


@app.route("/visits/<vid>/reschedule", methods=["POST"])
def reschedule_visit(vid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    body = require_body()
    new_raw = req_str(body, "new_scheduled_date")
    # State precondition (priority 5).
    if visit["status"] != "WEATHER_HOLD":
        raise err(ERR_INVALID_STATE, "Visit is not WEATHER_HOLD.")
    # Reschedule limit (priority 9): reschedule_count < 3 before the reschedule.
    if visit["reschedule_count"] >= S.RESCHEDULE_LIMIT:
        raise err(ERR_RESCHEDULE_LIMIT, "Visit has already been rescheduled 3 times.")
    new_date = parse_date(new_raw)
    held = parse_date(visit["scheduled_date"])
    sub = db.subscriptions.get(visit["subscription_id"])
    # Date temporal check (priority 10): strictly after held date, <= season_end.
    if not (new_date > held):
        raise err(ERR_DATE_OUT_OF_SEASON, "new_scheduled_date must be strictly after the held date.")
    if sub is not None and new_date > parse_date(sub["season_end_date"]):
        raise err(ERR_DATE_OUT_OF_SEASON, "new_scheduled_date must be on or before season_end_date.")
    # No qualifying weather event on the new date for the property's region.
    prop = _visit_property(visit)
    region = prop["service_region_code"] if prop else None
    for ev in db.weather_events.values():
        if (ev["region_code"] == region
                and ev["event_date"] == new_raw
                and ev["severity"] in S.QUALIFYING_SEVERITIES):
            raise err(ERR_DATE_OUT_OF_SEASON, "A qualifying weather event exists on the new date.")
    visit["scheduled_date"] = new_raw
    visit["reschedule_count"] += 1
    visit["status"] = "SCHEDULED"
    db.touch(visit)
    return success(plain(visit))


@app.route("/visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    assert_account_holder_owns(role, uid, visit_owner_id(visit))
    # State precondition (priority 5).
    if visit["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not SCHEDULED.")
    # Only SPECIAL_EVENT visits may be individually cancelled.
    if visit["visit_kind"] != "SPECIAL_EVENT":
        raise err(ERR_INVALID_STATE, "Only SPECIAL_EVENT visits may be individually cancelled.")
    visit["status"] = "CANCELLED"
    db.touch(visit)
    return success(plain(visit))


@app.route("/visits/<vid>/application-logs", methods=["POST"])
def create_application_log(vid):
    role, uid = get_identity()
    require_role(role, ["CrewTech", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    body = require_body()
    treatment_zone_id = req_str(body, "treatment_zone_id")
    product_code = req_enum(body, "product_code", {"BIFEN_IT", "TALSTAR", "ESSENTRIA_IC3"})
    gallons_applied = req_number(body, "gallons_applied", gt=0)
    logged_by_tech_id = req_str(body, "logged_by_tech_id")
    # Existence: zone.
    zone = must_get(db.treatment_zones, treatment_zone_id)
    # CrewTech ownership: acting tech must be the crew on the visit's route.
    crew_owns_visit_route(role, uid, visit)
    # Referential safety (priority 12): zone belongs to the same property as the
    # visit's subscription and is ACTIVE.
    prop = _visit_property(visit)
    if prop is None or zone["property_id"] != prop["id"] or zone["status"] != "ACTIVE":
        raise err(ERR_ZONE_NOT_TREATABLE, "Zone is not a treatable ACTIVE zone of this property.")

    log = {
        "visit_id": vid,
        "treatment_zone_id": treatment_zone_id,
        "product_code": product_code,
        "gallons_applied": gallons_applied,
        "logged_by_tech_id": logged_by_tech_id,
    }
    db.stamp_create_event(log)
    db.application_logs[log["id"]] = log
    return success(plain(log), status=201)


@app.route("/visits/<vid>/application-logs", methods=["GET"])
def list_application_logs(vid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin", "Dispatcher", "CrewTech"])
    visit = must_get(db.visits, vid)
    assert_account_holder_owns(role, uid, visit_owner_id(visit))
    limit, offset = parse_pagination()
    items = [l for l in db.application_logs.values() if l["visit_id"] == vid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(l) for l in page], limit, offset, total)


@app.route("/application-logs/<lid>", methods=["GET"])
def get_application_log(lid):
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher", "CrewTech"])
    log = must_get(db.application_logs, lid)
    return success(plain(log))


@app.route("/application-logs", methods=["GET"])
def list_all_application_logs():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher"])
    limit, offset = parse_pagination()
    items = list(db.application_logs.values())
    if "treatment_zone_id" in request.args:
        items = [l for l in items if l["treatment_zone_id"] == request.args.get("treatment_zone_id")]
    if "logged_by_tech_id" in request.args:
        items = [l for l in items if l["logged_by_tech_id"] == request.args.get("logged_by_tech_id")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(l) for l in page], limit, offset, total)


@app.route("/visits/<vid>/complete", methods=["POST"])
def complete_visit(vid):
    role, uid = get_identity()
    require_role(role, ["CrewTech", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    # State precondition (priority 5).
    if visit["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Visit is not DISPATCHED.")
    # CrewTech ownership: acting tech == Crew assigned to the visit's route.
    crew_owns_visit_route(role, uid, visit)
    # Business rule (priority 17): >= 1 application log.
    logs = [l for l in db.application_logs.values() if l["visit_id"] == vid]
    if len(logs) < 1:
        raise err(ERR_NO_APPLICATION_LOGGED, "Visit has no application logs recorded.")
    visit["completed_at_date"] = clock.today().isoformat()
    visit["status"] = "COMPLETED"
    sub = db.subscriptions.get(visit["subscription_id"])
    # PER_VISIT billing: issue invoice (RETREAT never bills).
    if sub is not None and sub["billing_mode"] == "PER_VISIT":
        plan = db.service_plans.get(sub["service_plan_id"])
        prop = db.properties.get(sub["property_id"])
        if plan is not None and prop is not None:
            S.issue_per_visit_invoice(visit, sub, plan, prop)
    db.touch(visit)
    return success(plain(visit))


@app.route("/visits/<vid>/request-retreat", methods=["POST"])
def request_retreat(vid):
    role, uid = get_identity()
    require_role(role, ["AccountHolder", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    assert_account_holder_owns(role, uid, visit_owner_id(visit))
    # State precondition (priority 5).
    if visit["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Visit is not COMPLETED.")
    if visit["visit_kind"] != "RECURRING":
        raise err(ERR_INVALID_STATE, "Only RECURRING visits support the re-treat guarantee.")
    sub = db.subscriptions.get(visit["subscription_id"])
    plan = db.service_plans.get(sub["service_plan_id"]) if sub else None
    # Guarantee window (priority 11).
    if plan is None or not S.retreat_guarantee_window_open(visit, plan):
        raise err(ERR_GUARANTEE_EXPIRED, "Re-treat guarantee window has closed.")
    # No existing RETREAT child for this visit (priority 15).
    if _has_retreat_child(vid):
        raise err(ERR_RETREAT_ALREADY_EXISTS, "A re-treat already exists for this visit.")
    visit["status"] = "RETREAT_REQUESTED"
    db.touch(visit)
    return success(plain(visit))


@app.route("/visits/<vid>/schedule-retreat", methods=["POST"])
def schedule_retreat(vid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    body = require_body()
    retreat_raw = req_str(body, "retreat_date")
    # State precondition (priority 5).
    if visit["status"] != "RETREAT_REQUESTED":
        raise err(ERR_INVALID_STATE, "Visit is not RETREAT_REQUESTED.")
    retreat_date = parse_date(retreat_raw)
    sub = db.subscriptions.get(visit["subscription_id"])
    # Date temporal check (priority 10): strictly after logical date, <= season_end.
    if not (retreat_date > clock.today()):
        raise err(ERR_DATE_OUT_OF_SEASON, "retreat_date must be strictly after the current date.")
    if sub is not None and retreat_date > parse_date(sub["season_end_date"]):
        raise err(ERR_DATE_OUT_OF_SEASON, "retreat_date must be on or before season_end_date.")
    # No existing RETREAT child (priority 15).
    if _has_retreat_child(vid):
        raise err(ERR_RETREAT_ALREADY_EXISTS, "A re-treat already exists for this visit.")
    # Create the child RETREAT Visit under the same subscription.
    child = {
        "subscription_id": visit["subscription_id"],
        "visit_kind": "RETREAT",
        "scheduled_date": retreat_raw,
        "sequence_index": 0,
        "status": "SCHEDULED",
        "crew_route_id": None,
        "weather_event_id": None,
        "parent_visit_id": vid,
        "reschedule_count": 0,
        "completed_at_date": None,
    }
    db.stamp_create_full(child)
    db.visits[child["id"]] = child
    visit["status"] = "RETREAT_SCHEDULED"
    db.touch(visit)
    return success(plain(visit))


@app.route("/visits/<vid>/close-retreat", methods=["POST"])
def close_retreat(vid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    visit = must_get(db.visits, vid)
    # State precondition (priority 5).
    if visit["status"] != "RETREAT_SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not RETREAT_SCHEDULED.")
    # The child RETREAT visit must be COMPLETED.
    child = _retreat_child(vid)
    if child is None or child["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "The child re-treat visit is not COMPLETED.")
    visit["status"] = "COMPLETED"
    db.touch(visit)
    return success(plain(visit))


def _retreat_child(parent_id):
    for v in db.visits.values():
        if v["parent_visit_id"] == parent_id and v["visit_kind"] == "RETREAT":
            return v
    return None


def _has_retreat_child(parent_id):
    return _retreat_child(parent_id) is not None


# ===========================================================================
# Crew routes / dispatch
# ===========================================================================
@app.route("/crew-routes", methods=["POST"])
def create_crew_route():
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    body = require_body()
    crew_id = req_str(body, "crew_id")
    region_code = req_str(body, "region_code")
    route_date_raw = req_str(body, "route_date")
    crew = must_get(db.crews, crew_id)
    parse_date(route_date_raw)  # well-formedness
    # Referential (priority 13): region_code must equal crew home_region_code.
    if region_code != crew["home_region_code"]:
        raise err(ERR_REGION_MISMATCH, "Route region must equal the crew's home region.")
    route = {
        "crew_id": crew_id,
        "region_code": region_code,
        "route_date": route_date_raw,
        "status": "OPEN",
    }
    db.stamp_create_full(route)
    db.crew_routes[route["id"]] = route
    return success(crew_route_view(route), status=201)


@app.route("/crew-routes/<rid>", methods=["GET"])
def get_crew_route(rid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin", "CrewTech"])
    route = must_get(db.crew_routes, rid)
    return success(crew_route_view(route))


@app.route("/crew-routes/<rid>/summary", methods=["GET"])
def crew_route_summary(rid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    route = must_get(db.crew_routes, rid)
    return success(crew_route_view(route, include_load_factor=True))


@app.route("/crew-routes/<rid>/dispatch-visit", methods=["POST"])
def dispatch_visit(rid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    route = must_get(db.crew_routes, rid)
    body = require_body()
    visit_id = req_str(body, "visit_id")
    expected_version = req_int(body, "expected_crewroute_version")
    visit = must_get(db.visits, visit_id)
    # State precondition (priority 5): visit SCHEDULED and route OPEN.
    if visit["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not SCHEDULED.")
    if route["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Route is not OPEN.")
    # OCC (priority 6).
    if expected_version != route["version"]:
        raise err(ERR_STALE_VERSION, "Route version is stale.")
    # Referential (priority 13): route region == visit's property region; route
    # date == visit's scheduled_date.
    prop = _visit_property(visit)
    region = prop["service_region_code"] if prop else None
    if route["region_code"] != region or route["route_date"] != visit["scheduled_date"]:
        raise err(ERR_REGION_MISMATCH, "Route region/date does not match the visit.")
    # Capacity (priority 14).
    crew = db.crews.get(route["crew_id"])
    assigned = sum(
        1 for v in db.visits.values()
        if v["crew_route_id"] == rid and v["status"] in ("DISPATCHED", "COMPLETED")
    )
    capacity = crew["daily_capacity"] if crew else 0
    if capacity - assigned < 1:
        raise err(ERR_ROUTE_AT_CAPACITY, "Route is at capacity.")
    # Commit.
    visit["crew_route_id"] = rid
    visit["status"] = "DISPATCHED"
    db.touch(visit)
    # Recompute route derived fields (done at view-time) and bump route version.
    db.touch(route)
    return success(plain(visit))


@app.route("/crew-routes/<rid>/lock", methods=["POST"])
def lock_route(rid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    route = must_get(db.crew_routes, rid)
    if route["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Route is not OPEN.")
    route["status"] = "LOCKED"
    db.touch(route)
    return success(crew_route_view(route))


@app.route("/crew-routes/<rid>/close", methods=["POST"])
def close_route(rid):
    role, uid = get_identity()
    require_role(role, ["Dispatcher", "PlatformAdmin"])
    route = must_get(db.crew_routes, rid)
    # Generic state precondition (priority 5): route must be LOCKED.
    if route["status"] != "LOCKED":
        raise err(ERR_INVALID_STATE, "Route is not LOCKED.")
    # Specialized state-tier check (priority 19): every assigned visit resolved.
    for v in db.visits.values():
        if v["crew_route_id"] == rid and v["status"] not in ("COMPLETED", "SKIPPED"):
            raise err(ERR_ROUTE_NOT_EMPTY, "Route still has an unresolved visit.")
    route["status"] = "CLOSED"
    db.touch(route)
    return success(crew_route_view(route))


# ===========================================================================
# Weather feed
# ===========================================================================
@app.route("/weather-events", methods=["POST"])
def create_weather_event():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher"])
    body = require_body()
    region_code = req_str(body, "region_code")
    event_date_raw = req_str(body, "event_date")
    severity = req_enum(body, "severity", {"RAIN_LIGHT", "RAIN_HEAVY", "WIND_HIGH"})
    parse_date(event_date_raw)  # well-formedness
    event = {
        "region_code": region_code,
        "event_date": event_date_raw,
        "severity": severity,
    }
    db.stamp_create_full(event)
    db.weather_events[event["id"]] = event
    return success(plain(event), status=201)


@app.route("/weather-events/<wid>", methods=["GET"])
def get_weather_event(wid):
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin", "Dispatcher"])
    event = must_get(db.weather_events, wid)
    return success(plain(event))


# ===========================================================================
# Invoices / billing
# ===========================================================================
@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    role, uid = get_identity()
    require_role(role, ["BillingAdmin", "AccountHolder", "PlatformAdmin"])
    inv = must_get(db.invoices, iid)
    assert_account_holder_owns(role, uid, invoice_owner_id(inv))
    return success(plain(inv))


@app.route("/subscriptions/<sid>/invoices", methods=["GET"])
def list_subscription_invoices(sid):
    role, uid = get_identity()
    require_role(role, ["BillingAdmin", "AccountHolder", "PlatformAdmin"])
    sub = must_get(db.subscriptions, sid)
    assert_account_holder_owns(role, uid, subscription_owner_id(sub))
    limit, offset = parse_pagination()
    items = [i for i in db.invoices.values() if i["subscription_id"] == sid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(i) for i in page], limit, offset, total)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    role, uid = get_identity()
    require_role(role, ["BillingAdmin", "PlatformAdmin"])
    limit, offset = parse_pagination()
    items = list(db.invoices.values())
    if "visit_id" in request.args:
        items = [i for i in items if i["visit_id"] == request.args.get("visit_id")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(i) for i in page], limit, offset, total)


@app.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    role, uid = get_identity()
    require_role(role, ["BillingAdmin", "PlatformAdmin"])
    inv = must_get(db.invoices, iid)
    body = require_body()
    paid_amount = req_int(body, "paid_amount_cents", minimum=0)
    # State precondition (priority 5).
    if inv["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Invoice is not ISSUED.")
    # Fiscal (priority 16): payment must be >= invoice amount.
    if paid_amount < inv["amount_cents"]:
        raise err(ERR_UNDERPAYMENT, "Payment is less than the invoice amount.")
    inv["paid_amount_cents"] = paid_amount
    inv["status"] = "PAID"
    overpayment = paid_amount - inv["amount_cents"]
    if overpayment > 0:
        sub = db.subscriptions.get(inv["subscription_id"])
        if sub is not None:
            S.credit_wallet(sub, overpayment)
    db.touch(inv)
    return success(plain(inv))


@app.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    role, uid = get_identity()
    require_role(role, ["BillingAdmin", "PlatformAdmin"])
    inv = must_get(db.invoices, iid)
    if inv["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Invoice is not ISSUED.")
    inv["status"] = "VOID"
    db.touch(inv)
    return success(plain(inv))


# ===========================================================================
# Test-driving (logical clock)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, uid = get_identity()
    require_role(role, ["PlatformAdmin"])
    body = require_body()
    to_iso = req_str(body, "to_iso8601")
    clock.set(parse_iso(to_iso))
    # Advancing the logical date past an ACTIVE subscription's season_end_date
    # auto-fires the ACTIVE -> OFF_SEASON transition (with cascade + pre-renewal).
    S.auto_roll_over_seasons()
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
