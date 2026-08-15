"""Routes: logical clock, stations, clocks, music categories, songs,
ratings books, rate card entries, syndication clearances."""
from flask import Blueprint, request

import store
from helpers import (DAYPARTS, err, get_body, opt_number, paginate,
                     parse_iso8601, req_date, req_enum, req_int, req_number,
                     req_present, req_str, req_weekday_set, require_role,
                     success_object)
from logic import (find, ser_clearance, ser_clock, ser_category,
                   ser_rate_card, ser_ratings_book, ser_song, ser_station,
                   stamp_new, touch)

bp = Blueprint("core", __name__)

ALL = ("ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
       "BillingAdmin")


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    raw = req_present(body, "to_iso8601")
    dt = parse_iso8601(raw)
    require_role(*ALL)
    store.set_clock(dt, raw)
    return success_object({"current_utc": raw}, 200)


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
@bp.post("/stations")
def create_station():
    body = get_body()
    call_sign = req_str(body, "call_sign")
    market_name = req_str(body, "market_name")
    fallback = opt_number(body, "default_share_fallback")
    require_role("SalesManager")
    rec = {"id": store.new_id(), "call_sign": call_sign,
           "market_name": market_name,
           "default_share_fallback": 1.0 if fallback is None else fallback}
    stamp_new(rec)
    store.stations[rec["id"]] = rec
    return success_object(ser_station(rec), 201)


@bp.get("/stations/<sid>")
def get_station(sid):
    require_role(*ALL)
    return success_object(ser_station(find(store.stations, sid)), 200)


@bp.get("/stations")
def list_stations():
    require_role(*ALL)
    return paginate(list(store.stations.values()), ser_station)


# ---------------------------------------------------------------------------
# Format clocks
# ---------------------------------------------------------------------------
_SLOT_TYPES = {"MUSIC", "SPOT_BREAK", "LIVE_READ_WINDOW"}


def _validate_slots(body):
    raw = req_present(body, "slots")
    if not isinstance(raw, list):
        err("ERR_BAD_REQUEST", "Field slots must be an array")
    seen = set()
    slots = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            err("ERR_BAD_REQUEST", f"slots[{i}] must be an object")
        slot_type = req_enum(entry, "slot_type", _SLOT_TYPES)
        hour = req_int(entry, "hour", minimum=0, maximum=23)
        cap_units = req_int(entry, "capacity_units", minimum=0)
        cap_seconds = req_int(entry, "capacity_seconds", minimum=0)
        key = (slot_type, hour)
        if key in seen:
            err("ERR_BAD_REQUEST",
                "At most one slot per (slot_type, hour) pair")
        seen.add(key)
        slots.append({"slot_type": slot_type, "hour": hour,
                      "capacity_units": cap_units,
                      "capacity_seconds": cap_seconds})
    return slots


@bp.post("/clocks")
def create_clock():
    body = get_body()
    station_id = req_str(body, "station_id")
    name = req_str(body, "name")
    weekdays = req_weekday_set(body, "applies_weekdays")
    slots = _validate_slots(body)
    require_role("ProgramDirector")
    find(store.stations, station_id)
    rec = {"id": store.new_id(), "station_id": station_id, "name": name,
           "applies_weekdays": weekdays, "slots": slots, "status": "DRAFT"}
    stamp_new(rec)
    store.clocks[rec["id"]] = rec
    return success_object(ser_clock(rec), 201)


@bp.get("/clocks/<cid>")
def get_clock(cid):
    require_role(*ALL)
    return success_object(ser_clock(find(store.clocks, cid)), 200)


@bp.get("/clocks")
def list_clocks():
    require_role(*ALL)
    recs = list(store.clocks.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_clock)


@bp.post("/clocks/<cid>/activate")
def activate_clock(cid):
    require_role("ProgramDirector")
    clock = find(store.clocks, cid)
    if clock["status"] != "DRAFT":
        err("ERR_INVALID_STATE",
            "Clock activate requires current status DRAFT")
    mine = set(clock["applies_weekdays"])
    for other in store.clocks.values():
        if (other["id"] != clock["id"]
                and other["station_id"] == clock["station_id"]
                and other["status"] == "ACTIVE"
                and mine & set(other["applies_weekdays"])):
            err("ERR_CLOCK_WEEKDAY_OVERLAP",
                "Another ACTIVE clock of this station overlaps weekdays")
    clock["status"] = "ACTIVE"
    touch(clock)
    return success_object(ser_clock(clock), 200)


@bp.post("/clocks/<cid>/retire")
def retire_clock(cid):
    require_role("ProgramDirector")
    clock = find(store.clocks, cid)
    if clock["status"] not in ("DRAFT", "ACTIVE"):
        err("ERR_INVALID_STATE",
            "Clock retire requires status DRAFT or ACTIVE")
    clock["status"] = "RETIRED"
    touch(clock)
    return success_object(ser_clock(clock), 200)


# ---------------------------------------------------------------------------
# Music categories
# ---------------------------------------------------------------------------
@bp.post("/music-categories")
def create_category():
    body = get_body()
    station_id = req_str(body, "station_id")
    code = req_str(body, "code")
    min_song = req_int(body, "min_song_separation_min", minimum=0)
    min_artist = req_int(body, "min_artist_separation_min", minimum=0)
    max_spins = req_int(body, "max_spins_per_day", minimum=1)
    require_role("ProgramDirector")
    find(store.stations, station_id)
    rec = {"id": store.new_id(), "station_id": station_id, "code": code,
           "min_song_separation_min": min_song,
           "min_artist_separation_min": min_artist,
           "max_spins_per_day": max_spins, "status": "ACTIVE"}
    stamp_new(rec)
    store.music_categories[rec["id"]] = rec
    return success_object(ser_category(rec), 201)


@bp.get("/music-categories/<cid>")
def get_category(cid):
    require_role(*ALL)
    return success_object(ser_category(find(store.music_categories, cid)),
                          200)


@bp.get("/music-categories")
def list_categories():
    require_role(*ALL)
    recs = list(store.music_categories.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_category)


@bp.post("/music-categories/<cid>/retire")
def retire_category(cid):
    require_role("ProgramDirector")
    cat = find(store.music_categories, cid)
    if cat["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Category retire requires status ACTIVE")
    cat["status"] = "RETIRED"
    touch(cat)
    return success_object(ser_category(cat), 200)


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------
@bp.post("/songs")
def create_song():
    body = get_body()
    station_id = req_str(body, "station_id")
    category_id = req_str(body, "category_id")
    title = req_str(body, "title")
    artist = req_str(body, "artist")
    duration_sec = req_int(body, "duration_sec", minimum=1)
    require_role("ProgramDirector")
    find(store.stations, station_id)
    find(store.music_categories, category_id)
    rec = {"id": store.new_id(), "station_id": station_id,
           "category_id": category_id, "title": title, "artist": artist,
           "duration_sec": duration_sec, "status": "ACTIVE"}
    stamp_new(rec)
    store.songs[rec["id"]] = rec
    return success_object(ser_song(rec), 201)


@bp.get("/songs/<sid>")
def get_song(sid):
    require_role(*ALL)
    return success_object(ser_song(find(store.songs, sid)), 200)


@bp.get("/songs")
def list_songs():
    require_role(*ALL)
    recs = list(store.songs.values())
    station_id = request.args.get("station_id")
    category_id = request.args.get("category_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if category_id is not None:
        recs = [r for r in recs if r["category_id"] == category_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_song)


@bp.post("/songs/<sid>/retire")
def retire_song(sid):
    require_role("ProgramDirector")
    song = find(store.songs, sid)
    if song["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Song retire requires status ACTIVE")
    song["status"] = "RETIRED"
    touch(song)
    return success_object(ser_song(song), 200)


# ---------------------------------------------------------------------------
# Ratings books
# ---------------------------------------------------------------------------
@bp.post("/ratings-books")
def create_ratings_book():
    body = get_body()
    station_id = req_str(body, "station_id")
    survey_name = req_str(body, "survey_name")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    share_value = req_number(body, "share_value", minimum=0,
                             exclusive_minimum=True)
    require_role("SalesManager")
    find(store.stations, station_id)
    if period_end < period_start:
        err("ERR_BAD_REQUEST", "period_end must be >= period_start")
    rec = {"id": store.new_id(), "station_id": station_id,
           "survey_name": survey_name,
           "period_start": period_start.isoformat(),
           "period_end": period_end.isoformat(),
           "share_value": share_value, "status": "DRAFT"}
    stamp_new(rec)
    store.ratings_books[rec["id"]] = rec
    return success_object(ser_ratings_book(rec), 201)


@bp.get("/ratings-books/<rid>")
def get_ratings_book(rid):
    require_role(*ALL)
    return success_object(ser_ratings_book(find(store.ratings_books, rid)),
                          200)


@bp.get("/ratings-books")
def list_ratings_books():
    require_role(*ALL)
    recs = list(store.ratings_books.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_ratings_book)


@bp.post("/ratings-books/<rid>/publish")
def publish_ratings_book(rid):
    require_role("SalesManager")
    book = find(store.ratings_books, rid)
    if book["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Publish requires status DRAFT")
    # Supersede cascade: every other PUBLISHED book of the station whose
    # period intersects this book's period -> SUPERSEDED.
    for other in store.ratings_books.values():
        if (other["id"] != book["id"]
                and other["station_id"] == book["station_id"]
                and other["status"] == "PUBLISHED"
                and other["period_start"] <= book["period_end"]
                and book["period_start"] <= other["period_end"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    book["status"] = "PUBLISHED"
    touch(book)
    return success_object(ser_ratings_book(book), 200)


# ---------------------------------------------------------------------------
# Rate card entries
# ---------------------------------------------------------------------------
@bp.post("/rate-card-entries")
def create_rate_card():
    body = get_body()
    station_id = req_str(body, "station_id")
    daypart = req_enum(body, "daypart", set(DAYPARTS))
    weekday_set = req_weekday_set(body, "weekday_set")
    base_rate = req_int(body, "base_rate_cents", minimum=1)
    min_rate = req_int(body, "min_rate_cents", minimum=1)
    effective_from = req_date(body, "effective_from")
    effective_to = req_date(body, "effective_to")
    require_role("SalesManager")
    find(store.stations, station_id)
    if min_rate > base_rate:
        err("ERR_BAD_REQUEST", "min_rate_cents must be <= base_rate_cents")
    if effective_to < effective_from:
        err("ERR_BAD_REQUEST", "effective_to must be >= effective_from")
    ef, et = effective_from.isoformat(), effective_to.isoformat()
    overlap = any(
        r["station_id"] == station_id and r["status"] == "ACTIVE"
        and r["daypart"] == daypart
        and set(r["weekday_set"]) & set(weekday_set)
        and r["effective_from"] <= et and ef <= r["effective_to"]
        for r in store.rate_card_entries.values())
    if overlap:
        err("ERR_RATE_WINDOW_OVERLAP",
            "Overlapping ACTIVE rate card entry on (station, daypart)")
    rec = {"id": store.new_id(), "station_id": station_id, "daypart": daypart,
           "weekday_set": weekday_set, "base_rate_cents": base_rate,
           "min_rate_cents": min_rate, "effective_from": ef,
           "effective_to": et, "status": "ACTIVE"}
    stamp_new(rec)
    store.rate_card_entries[rec["id"]] = rec
    return success_object(ser_rate_card(rec), 201)


@bp.get("/rate-card-entries/<rid>")
def get_rate_card(rid):
    require_role(*ALL)
    return success_object(ser_rate_card(find(store.rate_card_entries, rid)),
                          200)


@bp.get("/rate-card-entries")
def list_rate_cards():
    require_role(*ALL)
    recs = list(store.rate_card_entries.values())
    station_id = request.args.get("station_id")
    daypart = request.args.get("daypart")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if daypart is not None:
        recs = [r for r in recs if r["daypart"] == daypart]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_rate_card)


@bp.post("/rate-card-entries/<rid>/retire")
def retire_rate_card(rid):
    require_role("SalesManager")
    entry = find(store.rate_card_entries, rid)
    if entry["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Retire requires status ACTIVE")
    entry["status"] = "RETIRED"
    touch(entry)
    return success_object(ser_rate_card(entry), 200)


# ---------------------------------------------------------------------------
# Syndication clearances
# ---------------------------------------------------------------------------
@bp.post("/clearances")
def create_clearance():
    body = get_body()
    station_id = req_str(body, "station_id")
    program_name = req_str(body, "program_name")
    provider = req_str(body, "provider")
    weekday_set = req_weekday_set(body, "weekday_set")
    start_hour = req_int(body, "start_hour", minimum=0, maximum=23)
    duration_hours = req_int(body, "duration_hours", minimum=1)
    avails = req_int(body, "barter_avails_per_hour", minimum=1)
    effective_from = req_date(body, "effective_from")
    effective_to = req_date(body, "effective_to")
    require_role("ProgramDirector")
    find(store.stations, station_id)
    if start_hour + duration_hours > 24:
        err("ERR_BAD_REQUEST",
            "Clearance window may not wrap past hour 24")
    if effective_to < effective_from:
        err("ERR_BAD_REQUEST", "effective_to must be >= effective_from")
    rec = {"id": store.new_id(), "station_id": station_id,
           "program_name": program_name, "provider": provider,
           "weekday_set": weekday_set, "start_hour": start_hour,
           "duration_hours": duration_hours,
           "barter_avails_per_hour": avails,
           "effective_from": effective_from.isoformat(),
           "effective_to": effective_to.isoformat(), "status": "PENDING"}
    stamp_new(rec)
    store.clearances[rec["id"]] = rec
    return success_object(ser_clearance(rec), 201)


@bp.get("/clearances/<cid>")
def get_clearance(cid):
    require_role(*ALL)
    return success_object(ser_clearance(find(store.clearances, cid)), 200)


@bp.get("/clearances")
def list_clearances():
    require_role(*ALL)
    recs = list(store.clearances.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_clearance)


@bp.post("/clearances/<cid>/clear")
def clear_clearance(cid):
    require_role("ProgramDirector")
    clearance = find(store.clearances, cid)
    if clearance["status"] != "PENDING":
        err("ERR_INVALID_STATE", "Clear requires status PENDING")
    a_lo = clearance["start_hour"]
    a_hi = clearance["start_hour"] + clearance["duration_hours"]
    for other in store.clearances.values():
        if (other["id"] == clearance["id"]
                or other["station_id"] != clearance["station_id"]
                or other["status"] != "CLEARED"):
            continue
        if not (set(other["weekday_set"]) & set(clearance["weekday_set"])):
            continue
        b_lo = other["start_hour"]
        b_hi = other["start_hour"] + other["duration_hours"]
        # Half-open windows: adjacency (end == start) is allowed.
        if not (a_lo < b_hi and b_lo < a_hi):
            continue
        if not (other["effective_from"] <= clearance["effective_to"]
                and clearance["effective_from"] <= other["effective_to"]):
            continue
        err("ERR_CLEARANCE_WINDOW_OVERLAP",
            "Intersects a CLEARED clearance on weekday, hour window, and "
            "effective range")
    clearance["status"] = "CLEARED"
    touch(clearance)
    return success_object(ser_clearance(clearance), 200)


@bp.post("/clearances/<cid>/disaffirm")
def disaffirm_clearance(cid):
    require_role("ProgramDirector")
    clearance = find(store.clearances, cid)
    if clearance["status"] not in ("PENDING", "CLEARED"):
        err("ERR_INVALID_STATE",
            "Disaffirm requires status PENDING or CLEARED")
    today = store.current_date().isoformat()
    affected_logs = set()
    for avail in store.barter_avails.values():
        if (avail["clearance_id"] == clearance["id"]
                and avail["status"] == "SCHEDULED"
                and avail["air_date"] > today):
            avail["status"] = "CANCELLED"
            touch(avail)
            affected_logs.add(avail["log_id"])
    for log_id in affected_logs:
        log = store.logs.get(log_id)
        if log is not None:
            touch(log)  # occupancy counters recomputed
    clearance["status"] = "DISAFFIRMED"
    touch(clearance)
    return success_object(ser_clearance(clearance), 200)
