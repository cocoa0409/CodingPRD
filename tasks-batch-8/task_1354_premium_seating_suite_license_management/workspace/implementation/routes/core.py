"""Routes: clock, venues, suites, seasons, events."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from auth import require_roles, get_or_404, resolve_fk, ALL_ROLES
from domain import (pub_venue, pub_suite, pub_season, pub_event, now)
from response import success, success_list
from services.cascade import settle_season, event_cancelled, event_completed
from util import body, req_str, req_int, opt_int, req_enum, req_dt, paginate, fmt_ts

bp = Blueprint("core", __name__)

SUITE_TIERS = ("FOUNDERS", "PLATINUM", "GOLD", "SILVER")
EVENT_TYPES = ("REGULAR", "RIVALRY", "PLAYOFF", "CONCERT")


# ---------------------------------------------------------------- clock
@bp.post("/api/_clock/set_current_utc")
@require_roles("StadiumAdmin")
def set_clock():
    from util import parse_dt
    data = body()
    to = parse_dt(data.get("to_iso8601"), field="to_iso8601")
    db.set_clock(to)
    return success({"current_utc": fmt_ts(db.clock())}, status=200)


# ---------------------------------------------------------------- venues
@bp.post("/api/venues")
@require_roles("StadiumAdmin")
def create_venue():
    data = body()
    venue = db.new_entity({
        "name": req_str(data, "name"),
        "address": req_str(data, "address"),
        "default_catering_cutoff_hours": opt_int(data, "default_catering_cutoff_hours",
                                                 minimum=0, default=72),
    })
    db.insert("venues", venue)
    return success(pub_venue(venue), status=201)


@bp.get("/api/venues/<vid>")
@require_roles(*ALL_ROLES)
def get_venue(vid):
    return success(pub_venue(get_or_404("venues", vid)))


# ---------------------------------------------------------------- suites
@bp.post("/api/suites")
@require_roles("StadiumAdmin")
def create_suite():
    data = body()
    venue_id = data.get("venue_id")
    venue = resolve_fk("venues", venue_id)
    suite_code = req_str(data, "suite_code")
    tier = req_enum(data, "tier", SUITE_TIERS)
    capacity = req_int(data, "capacity_seats", minimum=1)
    base_fee = req_int(data, "base_annual_fee_cents", minimum=0)
    fb_min = req_int(data, "f_b_minimum_cents", minimum=0)
    for s in db.all_of("suites"):
        if s["venue_id"] == venue["id"] and s["suite_code"] == suite_code:
            raise errors.err_invalid_request("suite_code must be unique within the venue")
    suite = db.new_entity({
        "venue_id": venue["id"],
        "suite_code": suite_code,
        "tier": tier,
        "capacity_seats": capacity,
        "base_annual_fee_cents": base_fee,
        "f_b_minimum_cents": fb_min,
        "status": "AVAILABLE",
        "current_agreement_id": None,
    })
    db.insert("suites", suite)
    return success(pub_suite(suite), status=201)


@bp.get("/api/suites/<sid>")
@require_roles(*ALL_ROLES)
def get_suite(sid):
    return success(pub_suite(get_or_404("suites", sid)))


@bp.get("/api/suites")
@require_roles(*ALL_ROLES)
def list_suites():
    items = list(db.all_of("suites"))
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    tier = request.args.get("tier")
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if tier is not None:
        items = [s for s in items if s["tier"] == tier]
    page, meta = paginate(items, pub_suite)
    return success_list(page, meta)


@bp.post("/api/suites/<sid>/set_status")
@require_roles("StadiumAdmin")
def suite_set_status(sid):
    suite = get_or_404("suites", sid)
    target = body().get("target_status")
    if target not in ("AVAILABLE", "OUT_OF_SERVICE", "LICENSED"):
        raise errors.err_invalid_request("target_status must be a suite status")
    cur = suite["status"]
    if target == "OUT_OF_SERVICE":
        if cur == "LICENSED":
            raise errors.err_suite_licensed()
        if cur != "AVAILABLE":
            raise errors.err_invalid_state()
    elif target == "AVAILABLE":
        if cur != "OUT_OF_SERVICE":
            raise errors.err_invalid_state()
    else:  # LICENSED is system-managed only
        raise errors.err_invalid_state()
    suite["status"] = target
    db.touch(suite)
    return success(pub_suite(suite))


# ---------------------------------------------------------------- seasons
@bp.post("/api/seasons")
@require_roles("StadiumAdmin")
def create_season():
    data = body()
    venue = resolve_fk("venues", data.get("venue_id"))
    label = req_str(data, "label")
    starts_on = req_dt(data, "starts_on")
    ends_on = req_dt(data, "ends_on")
    opens = req_dt(data, "renewal_window_opens_on")
    closes = req_dt(data, "renewal_window_closes_on")
    if not ends_on > starts_on:
        raise errors.err_invalid_request("ends_on must be after starts_on")
    for s in db.all_of("seasons"):
        if s["venue_id"] == venue["id"] and s["label"] == label:
            raise errors.err_invalid_request("label must be unique within the venue")
    season = db.new_entity({
        "venue_id": venue["id"],
        "label": label,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "renewal_window_opens_on": opens,
        "renewal_window_closes_on": closes,
        "status": "DRAFT",
    })
    db.insert("seasons", season)
    return success(pub_season(season), status=201)


@bp.get("/api/seasons/<sid>")
@require_roles(*ALL_ROLES)
def get_season(sid):
    return success(pub_season(get_or_404("seasons", sid)))


@bp.get("/api/seasons")
@require_roles(*ALL_ROLES)
def list_seasons():
    items = list(db.all_of("seasons"))
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items, pub_season)
    return success_list(page, meta)


@bp.post("/api/seasons/<sid>/publish")
@require_roles("StadiumAdmin")
def publish_season(sid):
    season = get_or_404("seasons", sid)
    if season["status"] != "DRAFT":
        raise errors.err_invalid_state()
    if not season["ends_on"] > season["starts_on"]:
        raise errors.err_invalid_request("ends_on must be after starts_on")
    season["status"] = "PUBLISHED"
    db.touch(season)
    return success(pub_season(season))


@bp.post("/api/seasons/<sid>/settle")
@require_roles("FinanceController", "StadiumAdmin")
def settle(sid):
    season = get_or_404("seasons", sid)
    if season["status"] != "PUBLISHED":
        raise errors.err_invalid_state()
    if not now() > season["ends_on"]:
        raise errors.err_invalid_state("logical clock must be strictly after season ends_on")
    for e in db.all_of("events"):
        if e["season_id"] == sid and e["status"] not in ("COMPLETED", "CANCELLED"):
            raise errors.err_invalid_state("all events of the season must be COMPLETED or CANCELLED")
    settle_season(season)
    return success(pub_season(season))


# ---------------------------------------------------------------- events
@bp.post("/api/events")
@require_roles("StadiumAdmin")
def create_event():
    data = body()
    season = resolve_fk("seasons", data.get("season_id"))
    name = req_str(data, "name")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    starts_at = req_dt(data, "starts_at")
    duration = opt_int(data, "duration_hours", minimum=1, default=4)
    base_price = req_int(data, "rental_base_price_cents", minimum=0)
    cutoff = opt_int(data, "catering_cutoff_hours", minimum=0, default=None)
    if not (season["starts_on"] <= starts_at <= season["ends_on"]):
        raise errors.err_invalid_request("starts_at must fall within the season window")
    new_end = starts_at + timedelta(hours=duration)
    for e in db.all_of("events"):
        if e["status"] != "SCHEDULED":
            continue
        es = db.get("seasons", e["season_id"])
        if es is None or es["venue_id"] != season["venue_id"]:
            continue
        e_end = e["starts_at"] + timedelta(hours=e.get("duration_hours", 4))
        if starts_at < e_end and e["starts_at"] < new_end:
            raise errors.err_event_overlap()
    event = db.new_entity({
        "season_id": season["id"],
        "name": name,
        "event_type": event_type,
        "starts_at": starts_at,
        "duration_hours": duration,
        "rental_base_price_cents": base_price,
        "catering_cutoff_hours": cutoff,
        "status": "SCHEDULED",
    })
    db.insert("events", event)
    return success(pub_event(event), status=201)


@bp.get("/api/events/<eid>")
@require_roles(*ALL_ROLES)
def get_event(eid):
    return success(pub_event(get_or_404("events", eid)))


@bp.get("/api/events")
@require_roles(*ALL_ROLES)
def list_events():
    items = list(db.all_of("events"))
    season_id = request.args.get("season_id")
    event_type = request.args.get("event_type")
    status = request.args.get("status")
    if season_id is not None:
        items = [e for e in items if e["season_id"] == season_id]
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items, pub_event)
    return success_list(page, meta)


@bp.post("/api/events/<eid>/set_status")
@require_roles("StadiumAdmin")
def event_set_status(eid):
    event = get_or_404("events", eid)
    target = body().get("target_status")
    if target not in ("COMPLETED", "CANCELLED"):
        if target in ("SCHEDULED",):
            raise errors.err_invalid_state()
        raise errors.err_invalid_request("target_status must be COMPLETED or CANCELLED")
    if event["status"] != "SCHEDULED":
        raise errors.err_invalid_state()
    clock = now()
    if target == "CANCELLED":
        if not clock < event["starts_at"]:
            raise errors.err_invalid_state("event can only be cancelled before its start")
        event["status"] = "CANCELLED"
        db.touch(event)
        event_cancelled(event)
    else:
        end = event["starts_at"] + timedelta(hours=event.get("duration_hours", 4))
        if not clock >= end:
            raise errors.err_invalid_state("event can only complete after its occupancy interval")
        event["status"] = "COMPLETED"
        db.touch(event)
        event_completed(event)
    return success(pub_event(event))
