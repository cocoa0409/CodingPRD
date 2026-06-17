"""Agritourism Farm Attraction API — Flask entry point.

In-memory only. No seeding at startup. Boots clean on every invocation.
"""
import os

from flask import Flask, request

import db
from auth import get_identity, require_role
from common import (
    require_body, get_required, as_int, as_number, as_str, as_bool, as_enum,
    parse_dt, paginate, stamp_create, touch,
)
from errors import ApiError
from response import object_response, array_response, error_response
import domain
import serialize as S

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(400)
def handle_400(_e):
    return error_response("ERR_VALIDATION", "Malformed request body", 422)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_VALIDATION", f"Unexpected error: {err}", 422)


def body_json():
    if request.data and request.data.strip():
        try:
            parsed = request.get_json(force=True, silent=False)
        except Exception:
            raise ApiError("ERR_VALIDATION", "Malformed JSON body")
        if parsed is None:
            raise ApiError("ERR_VALIDATION", "Malformed JSON body")
        if not isinstance(parsed, dict):
            raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
        return parsed
    return {}


# =========================================================================== #
# Ownership helpers (priority 4 — ERR_NOT_OWNER)
# =========================================================================== #
def check_reservation_owner(reservation, user_id, role):
    if role == "Visitor" and reservation["visitor_id"] != user_id:
        raise ApiError("ERR_NOT_OWNER", "Visitor does not own this reservation")


def check_group_owner(group, user_id, role):
    if role == "GroupLeader" and group["group_leader_id"] != user_id:
        raise ApiError("ERR_NOT_OWNER", "GroupLeader does not own this group booking")


# =========================================================================== #
# FARM
# =========================================================================== #
@app.route("/farms", methods=["POST"])
def create_farm():
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    body = body_json()

    name = as_str(get_required(body, "name"), "name")
    timezone = body.get("timezone", "America/Chicago")
    if timezone is None:
        timezone = "America/Chicago"
    as_str(timezone, "timezone")
    parking_fee = body.get("parking_fee_cents", 1000)
    if parking_fee is None:
        parking_fee = 1000
    as_int(parking_fee, "parking_fee_cents", minimum=0)
    buffer_min = body.get("window_buffer_minutes", 30)
    if buffer_min is None:
        buffer_min = 30
    as_int(buffer_min, "window_buffer_minutes", minimum=0)

    farm = {
        "name": name,
        "timezone": timezone,
        "parking_fee_cents": parking_fee,
        "window_buffer_minutes": buffer_min,
        "operational_status": "OPEN",
        "active_weather_event_id": None,
        "refunds_issued_cents": 0,
    }
    stamp_create(farm)
    db.farms[farm["id"]] = farm
    return object_response(S.farm_out(farm), 201)


@app.route("/farms/<fid>", methods=["GET"])
def read_farm(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    farm = domain.get_farm(fid)
    return object_response(S.farm_out(farm), 200)


# =========================================================================== #
# WEATHER EVENTS (PRD §3.6)
# =========================================================================== #
@app.route("/farms/<fid>/weather-events", methods=["POST"])
def create_weather_event(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    farm = domain.get_farm(fid)
    body = body_json()

    kind = as_enum(get_required(body, "kind"), "kind", {"HOLD", "CLEARED", "CLOSURE"})
    note = body.get("note")
    if note is not None:
        as_str(note, "note")
    span_start = body.get("affected_span_start")
    span_end = body.get("affected_span_end")
    span_start_dt = parse_dt(span_start, "affected_span_start") if span_start is not None else None
    span_end_dt = parse_dt(span_end, "affected_span_end") if span_end is not None else None

    event = {
        "farm_id": fid,
        "kind": kind,
        "affected_span_start": span_start,
        "affected_span_end": span_end,
        "note": note,
        "resulting_status": None,
    }
    stamp_create(event, with_version=False)
    db.weather_events[event["id"]] = event

    _apply_weather(farm, event, kind, span_start_dt, span_end_dt)

    event["resulting_status"] = farm["operational_status"]
    return object_response(S.weather_event_out(event), 201)


def _apply_weather(farm, event, kind, span_start_dt, span_end_dt):
    status = farm["operational_status"]
    if kind == "HOLD":
        # PRD: HOLD on an OPEN farm. (precondition operational_status == OPEN)
        if status != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "HOLD only valid from OPEN")
        farm["operational_status"] = "WEATHER_HOLD"
        farm["active_weather_event_id"] = event["id"]
        touch(farm)
    elif kind == "CLEARED":
        if status == "WEATHER_HOLD":
            farm["operational_status"] = "OPEN"
            farm["active_weather_event_id"] = None
            touch(farm)
        elif status == "CLOSED":
            farm["operational_status"] = "OPEN"
            farm["active_weather_event_id"] = None
            touch(farm)
        else:
            raise ApiError("ERR_INVALID_STATE", "CLEARED only valid from WEATHER_HOLD or CLOSED")
    elif kind == "CLOSURE":
        if status == "CLOSED":
            raise ApiError("ERR_INVALID_STATE", "Farm already CLOSED")
        _closure_cascade(farm, event, span_start_dt, span_end_dt)
        farm["operational_status"] = "CLOSED"
        farm["active_weather_event_id"] = event["id"]
        touch(farm)


def _closure_cascade(farm, event, span_start_dt, span_end_dt):
    """3-level cascade (PRD §3.6), atomic within this request."""
    for window in list(db.admission_windows.values()):
        if window["farm_id"] != farm["id"]:
            continue
        if window["status"] == "CANCELLED":
            continue
        # Window's starts_at must fall within the affected span [start, end).
        if not _within_span(window["starts_at"], span_start_dt, span_end_dt):
            continue

        # L1: cancel the window.
        window["status"] = "CANCELLED"
        # L2: cancel live reservations on this window (PENDING/CONFIRMED).
        for res in list(db.reservations.values()):
            if res["window_id"] != window["id"]:
                continue
            if res["status"] in ("PENDING", "CONFIRMED"):
                domain.cancel_reservation_inventory_and_children(res, closure_cause=True)
        # Reset seat counters to 0 (PRD §3.6).
        window["seats_held"] = 0
        window["seats_committed"] = 0
        window["seats_available"] = max(0, window["capacity"])
        touch(window)


def _within_span(window_starts_at_iso, span_start_dt, span_end_dt):
    from common import parse_dt as _p
    ws = _p(window_starts_at_iso, "starts_at")
    if span_start_dt is not None and ws < span_start_dt:
        return False
    if span_end_dt is not None and ws >= span_end_dt:
        return False
    return True


@app.route("/farms/<fid>/weather-events", methods=["GET"])
def list_weather_events(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    domain.get_farm(fid)
    rows = [w for w in db.weather_events.values() if w["farm_id"] == fid]
    page, limit, offset, total = paginate(rows, request.args, newest_first=True)
    return array_response([S.weather_event_out(w) for w in page], limit, offset, total)


# =========================================================================== #
# PRICING POLICY (PRD §3.1)
# =========================================================================== #
@app.route("/farms/<fid>/pricing-policies", methods=["POST"])
def create_policy(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    domain.get_farm(fid)
    body = body_json()

    def reqint(name):
        return as_int(get_required(body, name), name, minimum=0)

    policy = {
        "farm_id": fid,
        "adult_admission_cents": reqint("adult_admission_cents"),
        "child_admission_cents": reqint("child_admission_cents"),
        "hayride_pass_cents": reqint("hayride_pass_cents"),
        "maze_pass_cents": reqint("maze_pass_cents"),
        "upick_pass_cents": reqint("upick_pass_cents"),
        "pumpkin_per_lb_cents": reqint("pumpkin_per_lb_cents"),
        "pumpkin_flat_each_cents": reqint("pumpkin_flat_each_cents"),
        "season_pass_price_cents": reqint("season_pass_price_cents"),
    }

    heavy = body.get("heavy_pumpkin_lb", 20)
    if heavy is None:
        heavy = 20
    as_number(heavy, "heavy_pumpkin_lb", gt=0)
    policy["heavy_pumpkin_lb"] = heavy

    grmin = body.get("group_rate_min_headcount", 15)
    if grmin is None:
        grmin = 15
    as_int(grmin, "group_rate_min_headcount", minimum=1)
    policy["group_rate_min_headcount"] = grmin

    gdp = body.get("group_discount_pct", 0.20)
    if gdp is None:
        gdp = 0.20
    as_number(gdp, "group_discount_pct", ge=0, lt=1)
    policy["group_discount_pct"] = gdp

    sdp = body.get("school_discount_pct", 0.35)
    if sdp is None:
        sdp = 0.35
    as_number(sdp, "school_discount_pct", ge=0, lt=1)
    policy["school_discount_pct"] = sdp

    policy["status"] = "DRAFT"
    stamp_create(policy)
    db.pricing_policies[policy["id"]] = policy
    return object_response(S.pricing_policy_out(policy), 201)


@app.route("/pricing-policies/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    policy = domain.get_policy(pid)
    if policy["status"] in ("ACTIVE", "SUPERSEDED"):
        raise ApiError("ERR_POLICY_ALREADY_ACTIVE",
                       "Policy is already ACTIVE or SUPERSEDED")
    # Demote any currently ACTIVE policy on the same farm.
    for other in db.pricing_policies.values():
        if (other["farm_id"] == policy["farm_id"] and other["id"] != policy["id"]
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            touch(other)
    policy["status"] = "ACTIVE"
    touch(policy)
    return object_response(S.pricing_policy_out(policy), 200)


@app.route("/pricing-policies/<pid>", methods=["GET"])
def read_policy(pid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    policy = domain.get_policy(pid)
    return object_response(S.pricing_policy_out(policy), 200)


@app.route("/farms/<fid>/pricing-policies", methods=["GET"])
def list_policies(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    domain.get_farm(fid)
    status = request.args.get("status")
    rows = [p for p in db.pricing_policies.values() if p["farm_id"] == fid]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.pricing_policy_out(p) for p in page], limit, offset, total)


# =========================================================================== #
# ADMISSION WINDOW (PRD §3.1)
# =========================================================================== #
@app.route("/farms/<fid>/admission-windows", methods=["POST"])
def create_window(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    farm = domain.get_farm(fid)
    body = body_json()

    starts_at = get_required(body, "starts_at")
    ends_at = get_required(body, "ends_at")
    capacity = as_int(get_required(body, "capacity"), "capacity", minimum=1)
    starts_dt = parse_dt(starts_at, "starts_at")
    ends_dt = parse_dt(ends_at, "ends_at")

    # priority 11: starts_at strictly before ends_at
    if not (starts_dt < ends_dt):
        raise ApiError("ERR_WINDOW_TIME_INVALID", "starts_at must be strictly before ends_at")

    # priority 11.5: buffered-interval overlap with existing non-cancelled windows
    from datetime import timedelta
    buffer = timedelta(minutes=farm["window_buffer_minutes"])
    for other in db.admission_windows.values():
        if other["farm_id"] != fid or other["status"] == "CANCELLED":
            continue
        o_start = parse_dt(other["starts_at"], "starts_at")
        o_end = parse_dt(other["ends_at"], "ends_at")
        # No collision only when one ends + buffer <= the other starts.
        no_collision = (ends_dt + buffer <= o_start) or (o_end + buffer <= starts_dt)
        if not no_collision:
            raise ApiError("ERR_WINDOW_OVERLAP", "Window collides with an existing window")

    window = {
        "farm_id": fid,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "seats_held": 0,
        "seats_committed": 0,
        "seats_available": capacity,
        "status": "SCHEDULED",
    }
    stamp_create(window)
    db.admission_windows[window["id"]] = window
    return object_response(S.window_out(window), 201)


@app.route("/admission-windows/<wid>", methods=["GET"])
def read_window(wid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    window = domain.get_window(wid)
    return object_response(S.window_out(window), 200)


@app.route("/farms/<fid>/admission-windows", methods=["GET"])
def list_windows(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    domain.get_farm(fid)
    status = request.args.get("status")
    rows = [w for w in db.admission_windows.values() if w["farm_id"] == fid]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.window_out(w) for w in page], limit, offset, total)


@app.route("/admission-windows/<wid>/mark-no-shows", methods=["POST"])
def mark_no_shows(wid):
    _, role = get_identity()
    require_role(role, {"GateAgent"})
    window = domain.get_window(wid)
    ends_dt = parse_dt(window["ends_at"], "ends_at")
    if ends_dt <= db.now():
        for res in list(db.reservations.values()):
            if res["window_id"] != wid:
                continue
            if res["status"] == "CONFIRMED":
                res["status"] = "NO_SHOW"
                touch(res)
        domain.reconcile_window(window)
    return object_response(S.window_out(window), 200)


@app.route("/admission-windows/<wid>/reservations", methods=["GET"])
def list_window_reservations(wid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    domain.get_window(wid)
    status = request.args.get("status")
    rows = [r for r in db.reservations.values() if r["window_id"] == wid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.reservation_out(r) for r in page], limit, offset, total)


@app.route("/admission-windows/<wid>/group-bookings", methods=["GET"])
def list_window_groups(wid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    domain.get_window(wid)
    status = request.args.get("status")
    rows = [g for g in db.group_bookings.values() if g["window_id"] == wid]
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.group_booking_out(g) for g in page], limit, offset, total)


# =========================================================================== #
# VISITOR (PRD §3.2)
# =========================================================================== #
@app.route("/visitors", methods=["POST"])
def create_visitor():
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    body = body_json()
    email = as_str(get_required(body, "email"), "email")
    full_name = as_str(get_required(body, "full_name"), "full_name")
    visitor = {
        "email": email,
        "full_name": full_name,
        "wallet_credit_cents": 0,
    }
    stamp_create(visitor)
    db.visitors[visitor["id"]] = visitor
    return object_response(S.visitor_out(visitor), 201)


@app.route("/visitors/<vid>", methods=["GET"])
def read_visitor(vid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    visitor = domain.get_visitor(vid)
    return object_response(S.visitor_out(visitor), 200)


@app.route("/visitors/<vid>/season-passes", methods=["GET"])
def list_visitor_passes(vid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    domain.get_visitor(vid)
    status = request.args.get("status")
    rows = [s for s in db.season_passes.values() if s["visitor_id"] == vid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.season_pass_out(s) for s in page], limit, offset, total)


@app.route("/visitors/<vid>/group-bookings", methods=["GET"])
def list_visitor_groups(vid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "GroupLeader", "Visitor"})
    domain.get_visitor(vid)
    status = request.args.get("status")
    rows = [g for g in db.group_bookings.values() if g["group_leader_id"] == vid]
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.group_booking_out(g) for g in page], limit, offset, total)


@app.route("/visitors/<vid>/reservations", methods=["GET"])
def list_visitor_reservations(vid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    domain.get_visitor(vid)
    status = request.args.get("status")
    rows = [r for r in db.reservations.values() if r["visitor_id"] == vid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.reservation_out(r) for r in page], limit, offset, total)


# =========================================================================== #
# SEASON PASS (PRD §3.2)
# =========================================================================== #
@app.route("/farms/<fid>/season-passes", methods=["POST"])
def issue_season_pass(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    farm = domain.get_farm(fid)
    body = body_json()
    visitor_id = as_str(get_required(body, "visitor_id"), "visitor_id")
    valid_from = get_required(body, "valid_from")
    valid_until = get_required(body, "valid_until")
    vf_dt = parse_dt(valid_from, "valid_from")
    vu_dt = parse_dt(valid_until, "valid_until")

    visitor = domain.get_visitor(visitor_id)  # existence (404)

    # priority 11.6: overlap with existing ACTIVE pass for same visitor+farm.
    for other in db.season_passes.values():
        if (other["farm_id"] == fid and other["visitor_id"] == visitor_id
                and other["status"] == "ACTIVE"):
            o_from = parse_dt(other["valid_from"], "valid_from")
            o_until = parse_dt(other["valid_until"], "valid_until")
            no_overlap = (vu_dt <= o_from) or (o_until <= vf_dt)
            if not no_overlap:
                raise ApiError("ERR_PASS_OVERLAP", "Overlapping ACTIVE pass for this visitor+farm")

    policy = domain.active_policy(fid)  # ERR_NO_ACTIVE_POLICY if none

    sp = {
        "farm_id": fid,
        "visitor_id": visitor_id,
        "purchase_price_cents": policy["season_pass_price_cents"],
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
        "visits_used": 0,
    }
    stamp_create(sp)
    db.season_passes[sp["id"]] = sp
    return object_response(S.season_pass_out(sp), 201)


@app.route("/season-passes/<sid>", methods=["GET"])
def read_season_pass(sid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    sp = domain.get_pass(sid)
    return object_response(S.season_pass_out(sp), 200)


@app.route("/farms/<fid>/season-passes", methods=["GET"])
def list_farm_passes(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    domain.get_farm(fid)
    status = request.args.get("status")
    visitor_id = request.args.get("visitor_id")
    rows = [s for s in db.season_passes.values() if s["farm_id"] == fid]
    if visitor_id is not None:
        rows = [s for s in rows if s["visitor_id"] == visitor_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.season_pass_out(s) for s in page], limit, offset, total)


@app.route("/season-passes/<sid>/revoke", methods=["POST"])
def revoke_season_pass(sid):
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    sp = domain.get_pass(sid)
    if sp["status"] == "REVOKED":
        raise ApiError("ERR_PASS_ALREADY_REVOKED", "Pass already REVOKED")
    sp["status"] = "REVOKED"
    touch(sp)
    return object_response(S.season_pass_out(sp), 200)


@app.route("/season-passes/<sid>/reservations", methods=["GET"])
def list_pass_reservations(sid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor"})
    domain.get_pass(sid)
    status = request.args.get("status")
    rows = [r for r in db.reservations.values() if r["season_pass_id"] == sid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.reservation_out(r) for r in page], limit, offset, total)


# =========================================================================== #
# RESERVATION (PRD §3.3)
# =========================================================================== #
def _pass_valid_for_window(sp, visitor_id, farm_id, window):
    """ERR_PASS_NOT_VALID checks: same visitor, same farm, ACTIVE, validity covers
    window.starts_at."""
    if sp["visitor_id"] != visitor_id:
        return False
    if sp["farm_id"] != farm_id:
        return False
    if sp["status"] != "ACTIVE":
        return False
    ws = parse_dt(window["starts_at"], "starts_at")
    vf = parse_dt(sp["valid_from"], "valid_from")
    vu = parse_dt(sp["valid_until"], "valid_until")
    return vf <= ws < vu


@app.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = get_identity()
    require_role(role, {"Visitor"})
    body = body_json()

    window_id = as_str(get_required(body, "window_id"), "window_id")
    visitor_id = as_str(get_required(body, "visitor_id"), "visitor_id")
    adult_count = as_int(get_required(body, "adult_count"), "adult_count", minimum=0)
    child_count = as_int(get_required(body, "child_count"), "child_count", minimum=0)
    expected_version = as_int(get_required(body, "expected_window_version"),
                              "expected_window_version", minimum=0)
    season_pass_id = body.get("season_pass_id")
    group_booking_id = body.get("group_booking_id")
    if season_pass_id is not None:
        as_str(season_pass_id, "season_pass_id")
    if group_booking_id is not None:
        as_str(group_booking_id, "group_booking_id")

    # priority 3: existence (path none; body FKs left-to-right as listed in payload)
    window = domain.get_window(window_id)
    domain.get_visitor(visitor_id)
    sp = domain.get_pass(season_pass_id) if season_pass_id else None
    group = domain.get_group(group_booking_id) if group_booking_id else None

    # priority 4: ownership — Visitor must own the reservation they create
    if visitor_id != user_id:
        raise ApiError("ERR_NOT_OWNER", "Visitor may only create their own reservation")

    farm = domain.get_farm(window["farm_id"])

    # priority 5: farm OPEN
    if farm["operational_status"] != "OPEN":
        raise ApiError("ERR_FARM_NOT_OPEN", "Farm is not OPEN")

    # priority 6.5: window not CANCELLED
    if window["status"] == "CANCELLED":
        raise ApiError("ERR_WINDOW_CANCELLED", "Window is CANCELLED")

    # priority 9: pass validity
    if sp is not None:
        if not _pass_valid_for_window(sp, visitor_id, farm["id"], window):
            raise ApiError("ERR_PASS_NOT_VALID", "Season pass is not valid for this reservation")

    # priority 10: group must be on the same window
    if group is not None:
        if group["window_id"] != window_id:
            raise ApiError("ERR_GROUP_WINDOW_MISMATCH",
                           "Group booking is on a different window")

    # priority 12: non-empty party
    participant_count = adult_count + child_count
    if participant_count < 1:
        raise ApiError("ERR_EMPTY_PARTY", "Reservation must have at least one participant")

    # priority 13: seats available
    if window["seats_available"] < participant_count:
        raise ApiError("ERR_WINDOW_SOLD_OUT", "Not enough seats available")

    # priority 14: OCC
    if expected_version != window["version"]:
        raise ApiError("ERR_WINDOW_VERSION_STALE", "Window version is stale")

    reservation = {
        "window_id": window_id,
        "visitor_id": visitor_id,
        "season_pass_id": season_pass_id,
        "group_booking_id": group_booking_id,
        "adult_count": adult_count,
        "child_count": child_count,
        "participant_count": participant_count,
        "admission_charge_cents": 0,
        "settled_charge_cents": 0,
        "expected_window_version": expected_version,
        "status": "PENDING",
        "checkout_finalized": False,
        "waiver_satisfied": False,
        "gross_cents": 0,
        "net_due_cents": 0,
    }
    stamp_create(reservation)
    db.reservations[reservation["id"]] = reservation

    # provisional admission charge (needs ACTIVE policy)
    policy = domain.active_policy(farm["id"])
    reservation["admission_charge_cents"] = domain.admission_charge(reservation, policy)

    # place hold + recompute seats; reconcile_window bumps the window version
    # once because the seat counts changed (PRD §2.4 / §3.3: create increments
    # the window version by one).
    domain.reconcile_window(window)

    return object_response(S.reservation_out(reservation), 201)


@app.route("/reservations/<rid>", methods=["GET"])
def read_reservation(rid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GroupLeader", "GateAgent"})
    res = domain.get_reservation(rid)
    return object_response(S.reservation_out(res), 200)


@app.route("/group-bookings/<gid>/reservations", methods=["GET"])
def list_group_reservations(gid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "GroupLeader"})
    domain.get_group(gid)
    status = request.args.get("status")
    rows = [r for r in db.reservations.values() if r["group_booking_id"] == gid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.reservation_out(r) for r in page], limit, offset, total)


@app.route("/reservations/<rid>/total", methods=["GET"])
def reservation_total(rid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GateAgent"})
    res = domain.get_reservation(rid)
    gross, net_due = domain.reservation_grand_total(res)
    # Read-only: populate computed fields on the returned snapshot, do not persist.
    snapshot = dict(res)
    snapshot["gross_cents"] = gross
    snapshot["net_due_cents"] = net_due
    return object_response(S.reservation_out(snapshot), 200)


@app.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    user_id, role = get_identity()
    require_role(role, {"Visitor"})
    res = domain.get_reservation(rid)
    check_reservation_owner(res, user_id, role)

    window = domain.get_window(res["window_id"])
    farm = domain.get_farm(window["farm_id"])

    # priority 5: farm OPEN
    if farm["operational_status"] != "OPEN":
        raise ApiError("ERR_FARM_NOT_OPEN", "Farm is not OPEN")
    # priority 6: valid state
    if res["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not PENDING")
    # priority 6.5: window not CANCELLED
    if window["status"] == "CANCELLED":
        raise ApiError("ERR_WINDOW_CANCELLED", "Window is CANCELLED")
    # priority 9: pass validity (if redeeming a pass)
    if res["season_pass_id"]:
        sp = domain.get_pass(res["season_pass_id"])
        if not _pass_valid_for_window(sp, res["visitor_id"], farm["id"], window):
            raise ApiError("ERR_PASS_NOT_VALID", "Season pass is not valid")

    res["status"] = "CONFIRMED"
    # re-pin provisional admission charge
    policy = domain.active_policy(farm["id"])
    res["admission_charge_cents"] = domain.admission_charge(res, policy)
    # pass visits_used += 1
    if res["season_pass_id"]:
        sp = domain.get_pass(res["season_pass_id"])
        sp["visits_used"] += 1
        touch(sp)
    touch(res)
    domain.reconcile_window(window)
    return object_response(S.reservation_out(res), 200)


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    user_id, role = get_identity()
    require_role(role, {"Visitor"})
    res = domain.get_reservation(rid)
    check_reservation_owner(res, user_id, role)

    if res["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Reservation is not PENDING or CONFIRMED")

    window = domain.get_window(res["window_id"])
    domain.cancel_reservation_inventory_and_children(res, closure_cause=False)
    domain.reconcile_window(window)
    return object_response(S.reservation_out(res), 200)


@app.route("/reservations/<rid>/check-in", methods=["POST"])
def check_in_reservation(rid):
    _, role = get_identity()
    require_role(role, {"GateAgent"})
    res = domain.get_reservation(rid)
    window = domain.get_window(res["window_id"])
    farm = domain.get_farm(window["farm_id"])

    # farm must be OPEN or WEATHER_HOLD (CLOSED blocks)
    if farm["operational_status"] == "CLOSED":
        raise ApiError("ERR_FARM_NOT_OPEN", "Farm is CLOSED")
    # priority 6: valid state
    if res["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not CONFIRMED")
    # window not CANCELLED
    if window["status"] == "CANCELLED":
        raise ApiError("ERR_WINDOW_CANCELLED", "Window is CANCELLED")
    # waiver must cover every participant
    domain.recompute_waiver_satisfied(res)
    if not res["waiver_satisfied"]:
        raise ApiError("ERR_WAIVER_INCOMPLETE", "A signed waiver must cover every participant")

    res["status"] = "CHECKED_IN"
    # settled admission charge (re-evaluates group status as of check-in)
    policy = domain.active_policy(farm["id"])
    res["settled_charge_cents"] = domain.admission_charge(res, policy)
    touch(res)
    domain.recompute_waiver_satisfied(res)
    domain.recompute_checkout_finalized(res)
    domain.reconcile_window(window)
    return object_response(S.reservation_out(res), 200)


@app.route("/reservations/<rid>/settle", methods=["POST"])
def settle_reservation(rid):
    _, role = get_identity()
    require_role(role, {"GateAgent"})
    res = domain.get_reservation(rid)

    if res["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not CHECKED_IN")

    domain.recompute_waiver_satisfied(res)
    domain.recompute_checkout_finalized(res)
    if not (res["checkout_finalized"] and res["waiver_satisfied"]):
        raise ApiError("ERR_CHECKOUT_NOT_FINALIZED",
                       "Both finalize legs must complete before settle")

    res["status"] = "SETTLED"
    touch(res)
    return object_response(S.reservation_out(res), 200)


# =========================================================================== #
# ACTIVITY PASS (PRD §3.5)
# =========================================================================== #
@app.route("/reservations/<rid>/activity-passes", methods=["POST"])
def attach_activity_pass(rid):
    user_id, role = get_identity()
    require_role(role, {"Visitor"})
    res = domain.get_reservation(rid)
    check_reservation_owner(res, user_id, role)
    body = body_json()

    activity = as_enum(get_required(body, "activity"), "activity",
                       {"HAYRIDE", "MAZE", "UPICK"})
    quantity = as_int(get_required(body, "quantity"), "quantity", minimum=1)

    window = domain.get_window(res["window_id"])
    policy = domain.active_policy(window["farm_id"])
    price_map = {
        "HAYRIDE": policy["hayride_pass_cents"],
        "MAZE": policy["maze_pass_cents"],
        "UPICK": policy["upick_pass_cents"],
    }
    unit_price = price_map[activity]

    ap = {
        "reservation_id": rid,
        "activity": activity,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": quantity * unit_price,
        "status": "ACTIVE",
    }
    stamp_create(ap)
    db.activity_passes[ap["id"]] = ap
    return object_response(S.activity_pass_out(ap), 201)


@app.route("/reservations/<rid>/activity-passes", methods=["GET"])
def list_activity_passes(rid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GateAgent"})
    domain.get_reservation(rid)
    status = request.args.get("status")
    rows = [a for a in db.activity_passes.values() if a["reservation_id"] == rid]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.activity_pass_out(a) for a in page], limit, offset, total)


# =========================================================================== #
# WAIVER (PRD §3.4)
# =========================================================================== #
@app.route("/reservations/<rid>/waivers", methods=["POST"])
def sign_waiver(rid):
    user_id, role = get_identity()
    require_role(role, {"Visitor"})
    res = domain.get_reservation(rid)
    check_reservation_owner(res, user_id, role)
    body = body_json()

    participant_name = as_str(get_required(body, "participant_name"), "participant_name")
    is_minor = body.get("is_minor", False)
    if is_minor is None:
        is_minor = False
    as_bool(is_minor, "is_minor")
    guardian_name = body.get("guardian_name")
    if guardian_name is not None:
        as_str(guardian_name, "guardian_name")

    # priority 8: a minor waiver must carry guardian_name
    if is_minor and not guardian_name:
        raise ApiError("ERR_GUARDIAN_REQUIRED", "Minor waiver requires guardian_name")

    waiver = {
        "reservation_id": rid,
        "participant_name": participant_name,
        "is_minor": is_minor,
        "guardian_name": guardian_name,
        "status": "SIGNED",
    }
    stamp_create(waiver)
    db.waivers[waiver["id"]] = waiver

    domain.recompute_waiver_satisfied(res)
    return object_response(S.waiver_out(waiver), 201)


@app.route("/reservations/<rid>/waivers", methods=["GET"])
def list_waivers(rid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GateAgent"})
    domain.get_reservation(rid)
    status = request.args.get("status")
    rows = [w for w in db.waivers.values() if w["reservation_id"] == rid]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.waiver_out(w) for w in page], limit, offset, total)


# =========================================================================== #
# PUMPKIN PURCHASE (PRD §3.4 / §3.5)
# =========================================================================== #
@app.route("/reservations/<rid>/pumpkin-purchases", methods=["POST"])
def add_pumpkin(rid):
    user_id, role = get_identity()
    require_role(role, {"Visitor"})
    res = domain.get_reservation(rid)
    check_reservation_owner(res, user_id, role)
    body = body_json()

    estimated_weight = as_number(get_required(body, "estimated_weight_lb"),
                                 "estimated_weight_lb", gt=0)

    window = domain.get_window(res["window_id"])
    policy = domain.active_policy(window["farm_id"])
    charge = domain.pumpkin_charge(estimated_weight, policy)

    pp = {
        "reservation_id": rid,
        "estimated_weight_lb": estimated_weight,
        "scale_weight_lb": None,
        "charge_cents": charge,
        "status": "ESTIMATED",
    }
    stamp_create(pp)
    db.pumpkin_purchases[pp["id"]] = pp

    domain.recompute_checkout_finalized(res)
    return object_response(S.pumpkin_out(pp), 201)


@app.route("/pumpkin-purchases/<pid>/weigh-out", methods=["POST"])
def weigh_out(pid):
    _, role = get_identity()
    require_role(role, {"GateAgent"})
    pp = domain.get_pumpkin(pid)
    body = body_json()

    scale_weight = as_number(get_required(body, "scale_weight_lb"),
                             "scale_weight_lb", gt=0)

    if pp["status"] in ("WEIGHED", "VOID"):
        raise ApiError("ERR_PUMPKIN_ALREADY_WEIGHED", "Pumpkin already weighed or void")

    res = domain.get_reservation(pp["reservation_id"])
    window = domain.get_window(res["window_id"])
    policy = domain.active_policy(window["farm_id"])

    pp["scale_weight_lb"] = scale_weight
    pp["charge_cents"] = domain.pumpkin_charge(scale_weight, policy)
    pp["status"] = "WEIGHED"
    touch(pp)

    domain.recompute_checkout_finalized(res)
    return object_response(S.pumpkin_out(pp), 200)


@app.route("/reservations/<rid>/pumpkin-purchases", methods=["GET"])
def list_pumpkins(rid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GateAgent"})
    domain.get_reservation(rid)
    status = request.args.get("status")
    rows = [p for p in db.pumpkin_purchases.values() if p["reservation_id"] == rid]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.pumpkin_out(p) for p in page], limit, offset, total)


# =========================================================================== #
# CONCESSION ORDER (PRD §3.5)
# =========================================================================== #
@app.route("/reservations/<rid>/concession-orders", methods=["POST"])
def add_concession(rid):
    user_id, role = get_identity()
    require_role(role, {"Visitor", "GateAgent"})
    res = domain.get_reservation(rid)
    # Only the entity-backed Visitor faces an ownership check; GateAgent is by-role.
    if role == "Visitor":
        check_reservation_owner(res, user_id, role)
    body = body_json()

    food_cents = body.get("food_cents", 0)
    if food_cents is None:
        food_cents = 0
    as_int(food_cents, "food_cents", minimum=0)
    vehicle_count = body.get("vehicle_count", 0)
    if vehicle_count is None:
        vehicle_count = 0
    as_int(vehicle_count, "vehicle_count", minimum=0)

    window = domain.get_window(res["window_id"])
    farm = domain.get_farm(window["farm_id"])
    parking_cents = vehicle_count * farm["parking_fee_cents"]

    co = {
        "reservation_id": rid,
        "food_cents": food_cents,
        "vehicle_count": vehicle_count,
        "parking_cents": parking_cents,
        "total_cents": food_cents + parking_cents,
        "status": "PAID",
    }
    stamp_create(co)
    db.concession_orders[co["id"]] = co
    return object_response(S.concession_out(co), 201)


@app.route("/reservations/<rid>/concession-orders", methods=["GET"])
def list_concessions(rid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "Visitor", "GateAgent"})
    domain.get_reservation(rid)
    status = request.args.get("status")
    rows = [c for c in db.concession_orders.values() if c["reservation_id"] == rid]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.concession_out(c) for c in page], limit, offset, total)


# =========================================================================== #
# GROUP BOOKING (PRD §3.7)
# =========================================================================== #
@app.route("/farms/<fid>/group-bookings", methods=["POST"])
def create_group(fid):
    user_id, role = get_identity()
    require_role(role, {"GroupLeader"})
    farm = domain.get_farm(fid)
    body = body_json()

    window_id = as_str(get_required(body, "window_id"), "window_id")
    group_leader_id = as_str(get_required(body, "group_leader_id"), "group_leader_id")
    kind = as_enum(get_required(body, "kind"), "kind",
                   {"FIELD_TRIP", "SCHOOL", "CORPORATE"})
    adult_count = as_int(get_required(body, "adult_count"), "adult_count", minimum=0)
    child_count = as_int(get_required(body, "child_count"), "child_count", minimum=0)
    parent_group_id = body.get("parent_group_id")
    if parent_group_id is not None:
        as_str(parent_group_id, "parent_group_id")

    # existence (left-to-right body FKs)
    window = domain.get_window(window_id)
    domain.get_visitor(group_leader_id)
    if parent_group_id is not None:
        domain.get_group(parent_group_id)

    # ownership — leader creates their own group
    if group_leader_id != user_id:
        raise ApiError("ERR_NOT_OWNER", "GroupLeader may only create their own booking")

    group = {
        "farm_id": fid,
        "window_id": window_id,
        "group_leader_id": group_leader_id,
        "parent_group_id": parent_group_id,
        "kind": kind,
        "adult_count": adult_count,
        "child_count": child_count,
        "headcount": adult_count + child_count,
        "quoted_total_cents": 0,
        "deposit_cents": 0,
        "expected_window_version": None,
        "status": "QUOTED",
    }
    stamp_create(group)
    db.group_bookings[group["id"]] = group

    policy = domain.active_policy(fid)
    group["quoted_total_cents"] = domain.group_quote(group, policy)
    return object_response(S.group_booking_out(group), 201)


@app.route("/group-bookings/<gid>", methods=["GET"])
def read_group(gid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "GroupLeader", "Visitor"})
    group = domain.get_group(gid)
    return object_response(S.group_booking_out(group), 200)


@app.route("/farms/<fid>/group-bookings", methods=["GET"])
def list_farm_groups(fid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "GroupLeader"})
    domain.get_farm(fid)
    status = request.args.get("status")
    kind = request.args.get("kind")
    rows = [g for g in db.group_bookings.values() if g["farm_id"] == fid]
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    if kind is not None:
        rows = [g for g in rows if g["kind"] == kind]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.group_booking_out(g) for g in page], limit, offset, total)


@app.route("/group-bookings/<gid>/sub-groups", methods=["GET"])
def list_sub_groups(gid):
    _, role = get_identity()
    require_role(role, {"FarmManager", "GroupLeader"})
    domain.get_group(gid)
    status = request.args.get("status")
    rows = [g for g in db.group_bookings.values() if g["parent_group_id"] == gid]
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response([S.group_booking_out(g) for g in page], limit, offset, total)


@app.route("/group-bookings/<gid>", methods=["PATCH"])
def edit_group(gid):
    user_id, role = get_identity()
    require_role(role, {"GroupLeader"})
    group = domain.get_group(gid)
    check_group_owner(group, user_id, role)

    if group["status"] != "REVISING":
        raise ApiError("ERR_GROUP_NOT_REVISABLE", "Group is not REVISING")

    body = body_json()
    if "adult_count" in body and body["adult_count"] is not None:
        group["adult_count"] = as_int(body["adult_count"], "adult_count", minimum=0)
    if "child_count" in body and body["child_count"] is not None:
        group["child_count"] = as_int(body["child_count"], "child_count", minimum=0)
    if "kind" in body and body["kind"] is not None:
        group["kind"] = as_enum(body["kind"], "kind", {"FIELD_TRIP", "SCHOOL", "CORPORATE"})
    group["headcount"] = group["adult_count"] + group["child_count"]
    touch(group)
    return object_response(S.group_booking_out(group), 200)


@app.route("/group-bookings/<gid>/revise", methods=["POST"])
def revise_group(gid):
    user_id, role = get_identity()
    require_role(role, {"GroupLeader"})
    group = domain.get_group(gid)
    check_group_owner(group, user_id, role)
    if group["status"] != "QUOTED":
        raise ApiError("ERR_GROUP_NOT_REVISABLE", "Group is not QUOTED")
    group["status"] = "REVISING"
    touch(group)
    return object_response(S.group_booking_out(group), 200)


@app.route("/group-bookings/<gid>/requote", methods=["POST"])
def requote_group(gid):
    user_id, role = get_identity()
    require_role(role, {"GroupLeader"})
    group = domain.get_group(gid)
    check_group_owner(group, user_id, role)
    if group["status"] != "REVISING":
        raise ApiError("ERR_GROUP_NOT_REVISABLE", "Group is not REVISING")
    group["status"] = "QUOTED"
    policy = domain.active_policy(group["farm_id"])
    group["quoted_total_cents"] = domain.group_quote(group, policy)
    touch(group)
    return object_response(S.group_booking_out(group), 200)


@app.route("/group-bookings/<gid>/confirm", methods=["POST"])
def confirm_group(gid):
    user_id, role = get_identity()
    require_role(role, {"GroupLeader"})
    group = domain.get_group(gid)
    check_group_owner(group, user_id, role)
    body = body_json()
    expected_version = as_int(get_required(body, "expected_window_version"),
                              "expected_window_version", minimum=0)

    window = domain.get_window(group["window_id"])
    farm = domain.get_farm(group["farm_id"])

    # priority 5: farm OPEN
    if farm["operational_status"] != "OPEN":
        raise ApiError("ERR_FARM_NOT_OPEN", "Farm is not OPEN")
    # priority 6: valid state
    if group["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Group is not QUOTED")
    # priority 6.5: window not CANCELLED
    if window["status"] == "CANCELLED":
        raise ApiError("ERR_WINDOW_CANCELLED", "Window is CANCELLED")
    # priority 12: headcount >= 1
    if group["headcount"] < 1:
        raise ApiError("ERR_EMPTY_PARTY", "Group is empty")
    # priority 13: seats available
    if window["seats_available"] < group["headcount"]:
        raise ApiError("ERR_WINDOW_SOLD_OUT", "Not enough seats for the group")
    # priority 14: OCC
    if expected_version != window["version"]:
        raise ApiError("ERR_WINDOW_VERSION_STALE", "Window version is stale")

    group["status"] = "CONFIRMED"
    group["expected_window_version"] = expected_version
    group["deposit_cents"] = domain.group_deposit(group["quoted_total_cents"])
    touch(group)

    # reconcile_window bumps the window version once because seats_committed
    # changed (PRD §2.4 / §3.7: confirm increments the window version by one).
    domain.reconcile_window(window)
    return object_response(S.group_booking_out(group), 200)


@app.route("/group-bookings/<gid>/cancel", methods=["POST"])
def cancel_group(gid):
    user_id, role = get_identity()
    require_role(role, {"GroupLeader"})
    group = domain.get_group(gid)
    check_group_owner(group, user_id, role)
    if group["status"] not in ("QUOTED", "REVISING"):
        raise ApiError("ERR_INVALID_STATE", "Only QUOTED/REVISING groups may be cancelled")
    group["status"] = "CANCELLED"
    touch(group)
    return object_response(S.group_booking_out(group), 200)


# =========================================================================== #
# TEST-DRIVING CLOCK (PRD §3.8)
# =========================================================================== #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, {"FarmManager"})
    body = body_json()
    to_iso = get_required(body, "to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    db.set_clock(dt)
    return object_response({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
