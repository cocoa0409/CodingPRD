from flask import Blueprint, request

import store
from common import (
    authorize, get_json, need, as_str, as_int,
    require_found, check_owner, parse_pagination, paginate,
)
from envelope import object_response, array_response
from errors import err
from timeutil import parse_dt

bp = Blueprint("tournaments", __name__)


def _parse_or_400(value, name):
    try:
        return parse_dt(as_str(value, name))
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", name + " must be an ISO 8601 instant")


@bp.post("/tournaments")
def create_tournament():
    authorize(["Clerk", "Manager"])
    body = get_json()
    sid = body.get("station_id")
    if sid is not None and sid not in store.stations:
        raise err("ERR_NOT_FOUND", "station_id does not exist")
    station_id = as_str(need(body, "station_id"), "station_id")
    title = as_str(need(body, "title"), "title")
    starts_raw = need(body, "starts_at")
    ends_raw = need(body, "ends_at")
    ro_raw = need(body, "registration_opens_at")
    rc_raw = need(body, "registration_closes_at")
    max_participants = as_int(need(body, "max_participants"), "max_participants")
    starts_dt = _parse_or_400(starts_raw, "starts_at")
    ends_dt = _parse_or_400(ends_raw, "ends_at")
    ro_dt = _parse_or_400(ro_raw, "registration_opens_at")
    rc_dt = _parse_or_400(rc_raw, "registration_closes_at")
    if not (ends_dt > starts_dt):
        raise err("ERR_VALIDATION", "ends_at must be strictly after starts_at")
    if not (rc_dt > ro_dt):
        raise err("ERR_VALIDATION", "registration_closes_at must be after registration_opens_at")
    if rc_dt > starts_dt:
        raise err("ERR_VALIDATION", "registration_closes_at must be <= starts_at")
    if max_participants <= 0:
        raise err("ERR_VALIDATION", "max_participants must be > 0")
    # Station double-booking (half-open intervals, no buffer).
    for other in store.tournaments.values():
        if other["station_id"] != station_id:
            continue
        o_starts = parse_dt(other["starts_at"])
        o_ends = parse_dt(other["ends_at"])
        if starts_dt < o_ends and o_starts < ends_dt:
            raise err("ERR_STATION_DOUBLE_BOOKED", "Tournament overlaps another on this station")
    t = store.make_record({
        "station_id": station_id,
        "title": title,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "registration_opens_at": ro_raw,
        "registration_closes_at": rc_raw,
        "max_participants": max_participants,
        "registered_count": 0,
        "registered_member_ids": [],
    })
    store.tournaments[t["id"]] = t
    return object_response(store.serialize(t), 201)


@bp.get("/tournaments/<tid>")
def get_tournament(tid):
    authorize(["Member", "Clerk", "Manager"])
    t = require_found(store.tournaments, tid)
    return object_response(store.serialize(t), 200)


@bp.get("/tournaments")
def list_tournaments():
    authorize(["Member", "Clerk", "Manager"])
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    matching = list(store.tournaments.values())
    if station_id is not None:
        matching = [t for t in matching if t["station_id"] == station_id]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(t) for t in window], limit, offset, total)


@bp.post("/tournaments/<tid>/register")
def register(tid):
    _, role = authorize(["Member", "Clerk", "Manager"])
    t = require_found(store.tournaments, tid)
    body = get_json()
    mid = body.get("member_id")
    if mid is not None and mid not in store.members:
        raise err("ERR_NOT_FOUND", "member_id does not exist")
    member_id = as_str(need(body, "member_id"), "member_id")
    check_owner(role, request.headers.get("X-User-ID"), member_id)
    now = store.clock_dt()
    opens = parse_dt(t["registration_opens_at"])
    closes = parse_dt(t["registration_closes_at"])
    if not (opens <= now < closes):
        raise err("ERR_REGISTRATION_CLOSED", "Outside the registration window")
    if t["registered_count"] >= t["max_participants"]:
        raise err("ERR_TOURNAMENT_FULL", "Tournament is at capacity")
    if member_id in t["registered_member_ids"]:
        raise err("ERR_ALREADY_REGISTERED", "Member already registered")
    t["registered_count"] += 1
    t["registered_member_ids"].append(member_id)
    store.touch(t)
    return object_response(store.serialize(t), 200)
