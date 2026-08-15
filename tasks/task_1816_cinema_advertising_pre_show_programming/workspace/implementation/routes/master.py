"""Master data: theaters, screens, features, showtimes, reels (PRD 3.1)."""
from datetime import timedelta

import db
import calc
from auth import require, ALL_ROLES
from envelope import success_object, success_list
from errors import not_found, conflict, ERR_SHOWTIME_OVERLAP
from serializers import (ser_theater, ser_screen, ser_feature, ser_showtime,
                         ser_reel)
from validate import (get_body, req_str, req_int, req_enum, req_datetime,
                      parse_datetime_value, parse_date_value, pagination)

from . import bp

MARKET_TIERS = {"MAJOR_METRO", "REGIONAL", "SMALL_MARKET"}
CONTENT_RATINGS = {"G", "PG", "PG13", "R", "NC17"}


# ------------------------------- Theaters -----------------------------------

@bp.post("/network/theaters")
def create_theater():
    require({"NetworkOps"})
    body = get_body()
    name = req_str(body, "name")
    tier = req_enum(body, "market_tier", MARKET_TIERS)
    rec = db.new_record()
    rec.update({"name": name, "market_tier": tier, "theater_status": "ACTIVE"})
    db.theaters[rec["id"]] = rec
    return success_object(ser_theater(rec), 201)


@bp.get("/network/theaters/<theater_id>")
def get_theater(theater_id):
    require(ALL_ROLES)
    t = db.theaters.get(theater_id)
    if t is None:
        raise not_found("theater not found")
    return success_object(ser_theater(t))


@bp.post("/network/theaters/<theater_id>/screens")
def create_screen(theater_id):
    require({"NetworkOps"})
    body = get_body()
    label = req_str(body, "auditorium_label")
    seats = req_int(body, "seat_count", minimum=1)
    t = db.theaters.get(theater_id)
    if t is None:
        raise not_found("theater not found")
    rec = db.new_record()
    rec.update({"theater_id": theater_id, "auditorium_label": label,
                "seat_count": seats, "screen_status": "ONLINE"})
    db.screens[rec["id"]] = rec
    return success_object(ser_screen(rec), 201)


@bp.get("/network/screens/<screen_id>")
def get_screen(screen_id):
    require(ALL_ROLES)
    s = db.screens.get(screen_id)
    if s is None:
        raise not_found("screen not found")
    return success_object(ser_screen(s))


@bp.get("/network/theaters/<theater_id>/screens")
def list_theater_screens(theater_id):
    require(ALL_ROLES)
    t = db.theaters.get(theater_id)
    if t is None:
        raise not_found("theater not found")
    limit, offset = pagination()
    items = sorted((s for s in db.screens.values()
                    if s["theater_id"] == theater_id),
                   key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_screen(s) for s in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


# ------------------------------- Features -----------------------------------

@bp.post("/network/features")
def create_feature():
    require({"NetworkOps"})
    body = get_body()
    title = req_str(body, "title")
    rating = req_enum(body, "content_rating", CONTENT_RATINGS)
    runtime = req_int(body, "runtime_minutes", minimum=1)
    if "release_date" not in body:
        from errors import bad_request
        raise bad_request("missing required field: release_date")
    release_raw = body["release_date"]
    release_dt = parse_date_value("release_date", release_raw)
    rec = db.new_record()
    rec.update({"title": title, "content_rating": rating,
                "runtime_minutes": runtime, "release_date": release_raw,
                "_release_dt": release_dt})
    db.features[rec["id"]] = rec
    return success_object(ser_feature(rec), 201)


@bp.get("/network/features/<feature_id>")
def get_feature(feature_id):
    require(ALL_ROLES)
    f = db.features.get(feature_id)
    if f is None:
        raise not_found("feature not found")
    return success_object(ser_feature(f))


# ------------------------------- Showtimes ----------------------------------

@bp.post("/network/screens/<screen_id>/showtimes")
def create_showtime(screen_id):
    require({"NetworkOps"})
    body = get_body()
    feature_id = req_str(body, "feature_id")
    starts_raw = req_datetime(body, "starts_at")
    starts_dt = parse_datetime_value("starts_at", starts_raw)

    screen = db.screens.get(screen_id)
    if screen is None:
        raise not_found("screen not found")
    feature = db.features.get(feature_id)
    if feature is None:
        raise not_found("feature not found")

    # Constraint tier: buffered overlap on the screen (TURNAROUND_MINUTES=30).
    # Conflict iff new_start < existing_end+30m AND existing_start < new_end+30m;
    # an exactly 30-minute gap is allowed.
    buf = timedelta(minutes=calc.TURNAROUND_MINUTES)
    new_end = starts_dt + timedelta(minutes=feature["runtime_minutes"])
    for st in db.showtimes.values():
        if st["screen_id"] != screen_id:
            continue
        ex_feature = db.features[st["feature_id"]]
        ex_start = st["_starts_dt"]
        ex_end = ex_start + timedelta(minutes=ex_feature["runtime_minutes"])
        if starts_dt < ex_end + buf and ex_start < new_end + buf:
            raise conflict(ERR_SHOWTIME_OVERLAP,
                           "showtime violates the screen's buffered-overlap rule")

    theater = db.theaters[screen["theater_id"]]
    daypart = calc.daypart_of(starts_dt)
    forecast = calc.forecast_attendance(
        screen["seat_count"], theater["market_tier"], daypart,
        feature["content_rating"], starts_dt.date(), feature["_release_dt"])

    rec = db.new_record()
    rec.update({"screen_id": screen_id, "feature_id": feature_id,
                "starts_at": starts_raw, "_starts_dt": starts_dt,
                "daypart": daypart, "forecast_attendance": forecast,
                "actual_attendance": None})
    db.showtimes[rec["id"]] = rec

    # Side effect: auto-create the ASSEMBLING pre-show reel (version 1).
    reel = db.new_record()
    reel.update({"showtime_id": rec["id"], "reel_status": "ASSEMBLING",
                 "capacity_seconds": calc.REEL_CAPACITY_SECONDS,
                 "national_pool_seconds": calc.NATIONAL_POOL_SECONDS,
                 "local_pool_seconds": calc.LOCAL_POOL_SECONDS,
                 "national_used_seconds": 0, "local_used_seconds": 0})
    db.reels[reel["id"]] = reel

    return success_object(ser_showtime(rec), 201)


@bp.get("/network/showtimes/<showtime_id>")
def get_showtime(showtime_id):
    require(ALL_ROLES)
    st = db.showtimes.get(showtime_id)
    if st is None:
        raise not_found("showtime not found")
    return success_object(ser_showtime(st))


@bp.get("/network/showtimes")
def list_showtimes():
    require(ALL_ROLES)
    limit, offset = pagination()
    screen_id = request_arg("screen_id")
    feature_id = request_arg("feature_id")
    items = sorted(db.showtimes.values(), key=lambda r: r["_seq"])
    if screen_id is not None:
        items = [s for s in items if s["screen_id"] == screen_id]
    if feature_id is not None:
        items = [s for s in items if s["feature_id"] == feature_id]
    total = len(items)
    page = [ser_showtime(s) for s in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


def request_arg(name):
    from flask import request
    return request.args.get(name)


@bp.get("/network/showtimes/<showtime_id>/reel")
def get_showtime_reel(showtime_id):
    require(ALL_ROLES)
    st = db.showtimes.get(showtime_id)
    if st is None:
        raise not_found("showtime not found")
    limit, offset = pagination()
    items = sorted((r for r in db.reels.values()
                    if r["showtime_id"] == showtime_id),
                   key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_reel(r) for r in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.get("/network/reels/<reel_id>")
def get_reel(reel_id):
    require(ALL_ROLES)
    r = db.reels.get(reel_id)
    if r is None:
        raise not_found("reel not found")
    return success_object(ser_reel(r))
