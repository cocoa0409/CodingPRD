"""Tracks, coaches, track days (with day lifecycle actions), rental blocks."""

import uuid

from flask import Blueprint

import db
import errors
import helpers as h
import response

bp = Blueprint("tracks", __name__)

ALL_ROLES = ("TrackOps", "SafetyOfficer", "Coach", "Organizer")


# ---------------------------------------------------------------------------
# Track
# ---------------------------------------------------------------------------
@bp.route("/tracks", methods=["POST"])
def create_track():
    h.require_roles("TrackOps")
    data = h.body()
    track = {
        "id": str(uuid.uuid4()),
        "name": h.req_string(data, "name"),
        "noise_limit_db": h.req_int(data, "noise_limit_db"),
        "run_group_capacity": h.req_int(data, "run_group_capacity"),
        "garage_bay_count": h.req_int(data, "garage_bay_count"),
        "paddock_stall_count": h.req_int(data, "paddock_stall_count"),
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.tracks[track["id"]] = track
    return response.success(h.serialize_track(track), 201)


@bp.route("/tracks/<tid>", methods=["GET"])
def get_track(tid):
    h.require_roles(*ALL_ROLES)
    track = h.resolve_track(tid)
    return response.success(h.serialize_track(track), 200)


# ---------------------------------------------------------------------------
# Coach
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/coaches", methods=["POST"])
def create_coach(tid):
    h.require_roles("TrackOps")
    track = h.resolve_track(tid)
    data = h.body()
    active = h.opt_bool(data, "active")
    coach = {
        "id": str(uuid.uuid4()),
        "track_id": track["id"],
        "full_name": h.req_string(data, "full_name"),
        "cert_level": h.req_enum(data, "cert_level", h.CERT_LEVELS),
        "active": True if active is None else active,
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.coaches[coach["id"]] = coach
    return response.success(h.serialize_coach(coach), 201)


@bp.route("/tracks/<tid>/coaches/<cid>", methods=["GET"])
def get_coach(tid, cid):
    h.require_roles(*ALL_ROLES)
    _, coach = h.resolve_coach(tid, cid)
    return response.success(h.serialize_coach(coach), 200)


@bp.route("/tracks/<tid>/coaches", methods=["GET"])
def list_coaches(tid):
    h.require_roles(*ALL_ROLES)
    track = h.resolve_track(tid)
    cert = h.query_enum("cert_level", h.CERT_LEVELS)
    active = h.parse_bool_param("active")
    limit, offset = h.pagination()
    items = [c for c in db.coaches.values() if c["track_id"] == track["id"]]
    if cert is not None:
        items = [c for c in items if c["cert_level"] == cert]
    if active is not None:
        items = [c for c in items if c["active"] == active]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_coach(c) for c in page], total, limit, offset)


# ---------------------------------------------------------------------------
# TrackDay
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days", methods=["POST"])
def create_track_day(tid):
    h.require_roles("TrackOps")
    track = h.resolve_track(tid)
    data = h.body()
    if "date" not in data:
        raise errors.invalid_request("field 'date' is required")
    day = {
        "id": str(uuid.uuid4()),
        "track_id": track["id"],
        "date": h.validate_date(data["date"], "date"),
        "status": "SCHEDULED",
        "posture": "NORMAL",
        "weather_flag": "CLEAR",
        "open_incident_count": 0,
        "noise_breach_count": 0,
        "ops_run_index": 0,
        "cancelled_reason": None,
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.track_days[day["id"]] = day
    return response.success(h.serialize_track_day(day), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>", methods=["GET"])
def get_track_day(tid, tdid):
    h.require_roles(*ALL_ROLES)
    _, day = h.resolve_track_day(tid, tdid)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days", methods=["GET"])
def list_track_days(tid):
    h.require_roles(*ALL_ROLES)
    track = h.resolve_track(tid)
    date = h.query_string("date")
    status = h.query_enum("status", h.TRACK_DAY_STATUSES)
    limit, offset = h.pagination()
    items = [d for d in db.track_days.values() if d["track_id"] == track["id"]]
    if date is not None:
        items = [d for d in items if d["date"] == date]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_track_day(d) for d in page], total, limit, offset)


def _touch_day(day):
    day["updated_at"] = h.now_str()
    day["version"] += 1


def _touch_session(session):
    session["updated_at"] = h.now_str()
    session["version"] += 1


@bp.route("/tracks/<tid>/track-days/<tdid>/open", methods=["POST"])
def open_track_day(tid, tdid):
    h.require_roles("TrackOps")
    _, day = h.resolve_track_day(tid, tdid)
    h.body()
    if day["status"] != "SCHEDULED":
        raise errors.invalid_state("track day must be SCHEDULED to open")
    day["status"] = "OPEN"
    h.recompute_posture(day)
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/weather_hold", methods=["POST"])
def weather_hold(tid, tdid):
    h.require_roles("TrackOps")
    _, day = h.resolve_track_day(tid, tdid)
    h.body()
    if day["status"] not in ("OPEN", "RUNNING") or day["weather_flag"] not in ("CLEAR", "WATCH"):
        raise errors.invalid_state("weather hold requires status OPEN or RUNNING and flag CLEAR or WATCH")
    was_running = day["status"] == "RUNNING"
    day["weather_flag"] = "WATCH"
    day["status"] = "WEATHER_HOLD"
    if was_running:
        for s in db.sessions.values():
            if s["track_day_id"] == day["id"] and s["status"] == "GREEN":
                s["status"] = "RED"
                _touch_session(s)
    h.recompute_posture(day)
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/weather_clear", methods=["POST"])
def weather_clear(tid, tdid):
    h.require_roles("TrackOps")
    _, day = h.resolve_track_day(tid, tdid)
    h.body()
    if day["status"] != "WEATHER_HOLD" or day["weather_flag"] != "WATCH":
        raise errors.invalid_state("weather clear requires status WEATHER_HOLD and flag WATCH")
    day["weather_flag"] = "CLEAR"
    day["status"] = "OPEN"
    h.recompute_posture(day)
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/resume", methods=["POST"])
def resume_track_day(tid, tdid):
    h.require_roles("SafetyOfficer")
    _, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    expected = h.req_int(data, "expected_track_day_version")
    if expected != day["version"]:
        raise errors.stale_version("expected_track_day_version does not match the track day's current version")
    h.recompute_noise_breach_count(day)
    if (day["status"] != "STOPPED"
            or day["open_incident_count"] != 0
            or day["weather_flag"] == "STOP"
            or day["noise_breach_count"] >= h.NOISE_BREACH_SUSPENSION_THRESHOLD):
        raise errors.invalid_state("resume requires STOPPED status, no open incidents, flag not STOP, breach count below threshold")
    day["status"] = "RUNNING"
    for s in db.sessions.values():
        if s["track_day_id"] == day["id"] and s["status"] == "RED":
            s["status"] = "GREEN"
            _touch_session(s)
    h.recompute_posture(day)
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/cancel", methods=["POST"])
def cancel_track_day(tid, tdid):
    h.require_roles("TrackOps")
    _, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    reason = h.req_enum(data, "reason", h.CANCEL_REASONS)
    status = day["status"]
    if status == "WEATHER_HOLD":
        if reason != "WEATHER":
            raise errors.invalid_state("from WEATHER_HOLD only reason WEATHER is accepted")
    elif status == "OPEN":
        if reason not in ("CUSTOMER", "SAFETY"):
            raise errors.invalid_state("from OPEN only reasons CUSTOMER and SAFETY are accepted")
        if reason == "SAFETY" and day["open_incident_count"] == 0:
            raise errors.invalid_state("SAFETY cancellation requires at least one open incident")
    elif status == "RUNNING":
        if reason not in ("WEATHER", "SAFETY"):
            raise errors.invalid_state("from RUNNING only reasons WEATHER and SAFETY are accepted")
    else:
        raise errors.invalid_state("track day cannot be cancelled from status %s" % status)
    was_running = status == "RUNNING"
    day["cancelled_reason"] = reason
    day["status"] = "CANCELLED"
    if was_running:
        for s in db.sessions.values():
            if s["track_day_id"] == day["id"] and s["status"] in ("GREEN", "RED"):
                s["status"] = "BLACK"
                s["ended_at_utc"] = h.now_str()
                _touch_session(s)
    # Cascade all non-terminal bookings on this day to CANCELLED with refunds.
    for booking in db.bookings.values():
        block = db.rental_blocks.get(booking["rental_block_id"])
        if block is None or block["track_day_id"] != day["id"]:
            continue
        if booking["approval_status"] in ("APPROVED", "PENDING"):
            h.cancel_booking_effects(booking, block, reason, day)
    h.recompute_posture(day)
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/close", methods=["POST"])
def close_track_day(tid, tdid):
    h.require_roles("TrackOps")
    _, day = h.resolve_track_day(tid, tdid)
    h.body()
    if day["status"] != "RUNNING":
        raise errors.invalid_state("track day must be RUNNING to close")
    if day["open_incident_count"] != 0:
        raise errors.invalid_state("cannot close with open incidents")
    for s in db.sessions.values():
        if s["track_day_id"] == day["id"] and s["status"] in ("GREEN", "RED"):
            raise errors.invalid_state("cannot close with sessions in GREEN or RED")
    h.recompute_posture(day)
    day["status"] = "CLOSED"
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/run_ops", methods=["POST"])
def run_ops(tid, tdid):
    h.require_roles("TrackOps")
    _, day = h.resolve_track_day(tid, tdid)
    h.body()
    day["ops_run_index"] += 1
    now_dt = h.parse_dt(h.now_str())
    for waiver in db.waivers.values():
        if h.parse_dt(waiver["expires_at_utc"]) < now_dt:
            driver = db.drivers.get(waiver["driver_id"])
            if driver is not None and driver["waiver_status"] != "EXPIRED":
                driver["waiver_status"] = "EXPIRED"
                driver["updated_at"] = h.now_str()
                driver["version"] += 1
                h.recompute_driver_cleared(driver)
    h.recompute_posture(day)
    _touch_day(day)
    return response.success(h.serialize_track_day(day), 200)


# ---------------------------------------------------------------------------
# RentalBlock
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks", methods=["POST"])
def create_rental_block(tid, tdid):
    h.require_roles("TrackOps")
    track, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    block_index = h.req_int(data, "block_index")
    start_minute = h.req_int(data, "start_minute")
    end_minute = h.req_int(data, "end_minute")
    max_group_size = h.req_int(data, "max_group_size")
    if end_minute <= start_minute:
        raise errors.invalid_request("end_minute must be greater than start_minute (half-open interval)")
    # Temporal overlap check is evaluated before the capacity check (PRD §3.2).
    for other in db.rental_blocks.values():
        if other["track_day_id"] != day["id"]:
            continue
        if start_minute < other["end_minute"] and other["start_minute"] < end_minute:
            raise errors.block_overlap()
    if max_group_size > track["run_group_capacity"]:
        raise errors.group_size_exceeds_track_cap()
    block = {
        "id": str(uuid.uuid4()),
        "track_day_id": day["id"],
        "block_index": block_index,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "max_group_size": max_group_size,
        "seats_reserved": 0,
        "seats_available": max_group_size,
        "status": "OPEN",
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.rental_blocks[block["id"]] = block
    return response.success(h.serialize_rental_block(block), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>", methods=["GET"])
def get_rental_block(tid, tdid, rbid):
    h.require_roles(*ALL_ROLES)
    _, _, block = h.resolve_rental_block(tid, tdid, rbid)
    return response.success(h.serialize_rental_block(block), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks", methods=["GET"])
def list_rental_blocks(tid, tdid):
    h.require_roles(*ALL_ROLES)
    _, day = h.resolve_track_day(tid, tdid)
    limit, offset = h.pagination()
    items = [b for b in db.rental_blocks.values() if b["track_day_id"] == day["id"]]
    items.sort(key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_rental_block(b) for b in page], total, limit, offset)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/close_block", methods=["POST"])
def close_rental_block(tid, tdid, rbid):
    h.require_roles("TrackOps")
    _, _, block = h.resolve_rental_block(tid, tdid, rbid)
    h.body()
    if block["status"] not in ("OPEN", "FULL"):
        raise errors.invalid_state("block must be OPEN or FULL to close")
    block["status"] = "CLOSED"
    block["updated_at"] = h.now_str()
    block["version"] += 1
    for booking in db.bookings.values():
        if booking["rental_block_id"] == block["id"] and booking["approval_status"] == "PENDING":
            booking["approval_status"] = "REJECTED"
            booking["updated_at"] = h.now_str()
            booking["version"] += 1
    return response.success(h.serialize_rental_block(block), 200)
