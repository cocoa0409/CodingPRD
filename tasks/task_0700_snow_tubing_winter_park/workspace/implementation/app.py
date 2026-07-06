"""Snow Tubing Winter Park API — Flask entry point.

In-memory store; no persistence. Boots empty on every process start.
"""
import os

from flask import Flask, request

from db import new_store
from errors import ApiError, ERRORS
from response import success, error_response
from middleware import authenticate, require_roles
from clock import parse_iso8601
from services.common import (
    make_record, touch, iso_z,
    require_present, as_int, as_str, as_enum, as_datetime,
)
from services.serialize import serialize
from services.pagination import paginate
from services import domain

app = Flask(__name__)
STORE = new_store()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    # Surface unexpected errors as invalid request to avoid 500s leaking.
    return error_response("ERR_INVALID_REQUEST", 422, f"Unexpected error: {e}")


def get_json():
    """Parse request JSON body, tolerating empty bodies."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def find_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found.")
    return rec


def park_or_404(pid):
    return find_or_404(STORE.parks, pid)


def auth_for(method, route_key):
    return authenticate(method, route_key)


# ===========================================================================
# Bootstrap: patrons & parks
# ===========================================================================
@app.route("/patrons", methods=["POST"])
def create_patron():
    caller = auth_for("POST", "/patrons")
    require_roles(caller, {"Anonymous", "ParkOperator"})
    body = get_json()
    full_name = as_str(body, "full_name")
    zip_code = as_str(body, "zip_code")
    birthdate = as_datetime(body, "birthdate")
    rec = make_record(STORE, "Patron", {
        "full_name": full_name,
        "zip_code": zip_code,
        "birthdate": iso_z(birthdate),
    })
    STORE.patrons[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/patrons/<pid>", methods=["GET"])
def get_patron(pid):
    caller = auth_for("GET", "/patrons/{id}")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    rec = find_or_404(STORE.patrons, pid)
    return success(serialize(rec), 200)


@app.route("/parks", methods=["POST"])
def create_park():
    caller = auth_for("POST", "/parks")
    require_roles(caller, {"Anonymous", "ParkOperator"})
    body = get_json()
    name = as_str(body, "name")
    tz = as_int(body, "timezone_offset_minutes", required=False, default=0)
    prefixes = body.get("resident_zip_prefixes", [])
    if prefixes is None:
        prefixes = []
    if not isinstance(prefixes, list) or any(not isinstance(p, str) for p in prefixes):
        raise ApiError("ERR_INVALID_REQUEST", 422, "resident_zip_prefixes must be an array of strings.")
    min_snow = as_int(body, "min_snow_depth_cm", required=False, default=15)
    max_wind = as_int(body, "max_safe_wind_kph", required=False, default=50)
    rec = make_record(STORE, "Park", {
        "name": name,
        "timezone_offset_minutes": tz,
        "resident_zip_prefixes": list(prefixes),
        "min_snow_depth_cm": min_snow,
        "max_safe_wind_kph": max_wind,
        "operational_posture": "OPEN",
        "open_lane_count": 0,
        "total_capacity_remaining": 0,
    })
    STORE.parks[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/parks/<pid>", methods=["GET"])
def get_park(pid):
    caller = auth_for("GET", "/parks/{id}")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    rec = park_or_404(pid)
    return success(serialize(rec), 200)


@app.route("/parks", methods=["GET"])
def list_parks():
    caller = auth_for("GET", "/parks")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    page, meta = paginate(list(STORE.parks.values()))
    return success([serialize(r) for r in page], 200, pagination=meta)


# ===========================================================================
# Lanes
# ===========================================================================
@app.route("/parks/<pid>/lanes", methods=["POST"])
def create_lane(pid):
    caller = auth_for("POST", "/parks/{id}/lanes")
    require_roles(caller, {"ParkOperator"})
    park = park_or_404(pid)
    body = get_json()
    label = as_str(body, "label")
    capacity = as_int(body, "rider_capacity_per_block", minimum=1)
    cycle = as_int(body, "conveyor_cycle_seconds", minimum=1)
    rec = make_record(STORE, "Lane", {
        "park_id": pid,
        "label": label,
        "rider_capacity_per_block": capacity,
        "conveyor_cycle_seconds": cycle,
        "status": "OPEN",
        "closure_reason": None,
    })
    STORE.lanes[rec["id"]] = rec
    # Recompute park aggregates + explicit version bump (endpoint side effect).
    domain.reconcile_park(STORE, park)
    touch(STORE, park)
    return success(serialize(rec), 201)


@app.route("/parks/<pid>/lanes", methods=["GET"])
def list_lanes(pid):
    caller = auth_for("GET", "/parks/{id}/lanes")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    park_or_404(pid)
    rows = [l for l in STORE.lanes.values() if l["park_id"] == pid]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/lanes/<lid>", methods=["GET"])
def get_lane(lid):
    caller = auth_for("GET", "/lanes/{id}")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    rec = find_or_404(STORE.lanes, lid)
    return success(serialize(rec), 200)


@app.route("/lanes/<lid>/groom", methods=["POST"])
def groom_lane(lid):
    caller = auth_for("POST", "/lanes/{id}/groom")
    require_roles(caller, {"ParkOperator"})
    lane = find_or_404(STORE.lanes, lid)
    if lane["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Lane must be OPEN to groom.")
    # PRD §3.1: grooming is permitted only when "no ACTIVE time block has committed
    # riders ON THAT LANE". A rider is pinned to a specific lane only by a BOARDED
    # ConveyorTurn (created at boarding); confirmed tickets commit to a BLOCK, not a
    # lane. So we reject only when a BOARDED turn on THIS lane sits in an ACTIVE block.
    park = STORE.parks.get(lane["park_id"])
    for turn in STORE.conveyor_turns.values():
        if turn["lane_id"] != lid or turn["state"] != "BOARDED":
            continue
        tb = STORE.time_blocks.get(turn["time_block_id"])
        if tb is not None and tb["status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Active block has committed riders on this lane.")
    lane["status"] = "GROOMING"
    lane["closure_reason"] = "MAINTENANCE"
    touch(STORE, lane)
    if park:
        domain.reconcile_park(STORE, park)
    return success(serialize(lane), 200)


@app.route("/lanes/<lid>/reopen", methods=["POST"])
def reopen_lane(lid):
    caller = auth_for("POST", "/lanes/{id}/reopen")
    require_roles(caller, {"ParkOperator"})
    lane = find_or_404(STORE.lanes, lid)
    if lane["status"] not in ("GROOMING", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Lane must be GROOMING or CLOSED to reopen.")
    park = STORE.parks.get(lane["park_id"])
    if park and park["operational_posture"] == "CLOSED":
        # Reopen requires posture != CLOSED.
        raise ApiError("ERR_INVALID_STATE", 409, "Park is CLOSED; cannot reopen lane.")
    lane["status"] = "OPEN"
    lane["closure_reason"] = None
    touch(STORE, lane)
    if park:
        domain.reconcile_park(STORE, park)
    return success(serialize(lane), 200)


@app.route("/lanes/<lid>/close", methods=["POST"])
def close_lane_endpoint(lid):
    caller = auth_for("POST", "/lanes/{id}/close")
    require_roles(caller, {"ParkOperator"})
    lane = find_or_404(STORE.lanes, lid)
    if lane["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Lane must be OPEN to close.")
    park = STORE.parks.get(lane["park_id"])
    # Manual close: closure_reason MAINTENANCE, cascade ticket expiry (no weather refund? -
    # PRD §3.6: manual lane close carries the same downward cascade, each creating a RefundEntry).
    domain.close_lane(STORE, lane, "MAINTENANCE", weather=True, expire_tickets=True)
    if park:
        domain.reconcile_park(STORE, park)
    return success(serialize(lane), 200)


# ===========================================================================
# Time blocks
# ===========================================================================
@app.route("/parks/<pid>/time-blocks", methods=["POST"])
def create_time_block(pid):
    caller = auth_for("POST", "/parks/{id}/time-blocks")
    require_roles(caller, {"ParkOperator"})
    park_or_404(pid)
    body = get_json()
    starts_at = as_datetime(body, "starts_at")
    ends_at = as_datetime(body, "ends_at")
    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_REQUEST", 422, "ends_at must be strictly after starts_at.")
    rec = make_record(STORE, "TimeBlock", {
        "park_id": pid,
        "starts_at": iso_z(starts_at),
        "ends_at": iso_z(ends_at),
        "status": "SCHEDULED",
        "committed_rider_count": 0,
    })
    rec["_starts_dt"] = starts_at
    rec["_ends_dt"] = ends_at
    STORE.time_blocks[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/parks/<pid>/time-blocks", methods=["GET"])
def list_time_blocks(pid):
    caller = auth_for("GET", "/parks/{id}/time-blocks")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    park_or_404(pid)
    rows = [t for t in STORE.time_blocks.values() if t["park_id"] == pid]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/time-blocks/<tid>", methods=["GET"])
def get_time_block(tid):
    caller = auth_for("GET", "/time-blocks/{id}")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    rec = find_or_404(STORE.time_blocks, tid)
    return success(serialize(rec), 200)


@app.route("/time-blocks/<tid>/activate", methods=["POST"])
def activate_time_block(tid):
    caller = auth_for("POST", "/time-blocks/{id}/activate")
    require_roles(caller, {"ParkOperator"})
    tb = find_or_404(STORE.time_blocks, tid)
    if tb["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Time block must be SCHEDULED to activate.")
    park = STORE.parks.get(tb["park_id"])
    # Posture gate (closed-park blocks activate) — priority 7.
    if park and park["operational_posture"] == "CLOSED":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park is CLOSED.")
    # Window check — priority 12.
    now = STORE.clock.now
    if not (tb["_starts_dt"] <= now < tb["_ends_dt"]):
        raise ApiError("ERR_BLOCK_WINDOW_CLOSED", 409, "Clock outside block window.")
    tb["status"] = "ACTIVE"
    touch(STORE, tb)
    # Activating a block changes which committed counts feed total_capacity_remaining.
    if park:
        domain.reconcile_park(STORE, park)
    return success(serialize(tb), 200)


@app.route("/time-blocks/<tid>/sweep", methods=["POST"])
def sweep_time_block(tid):
    caller = auth_for("POST", "/time-blocks/{id}/sweep")
    require_roles(caller, {"ParkOperator"})
    tb = find_or_404(STORE.time_blocks, tid)
    if tb["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Time block must be ACTIVE to sweep.")
    tb["status"] = "SWEPT"
    touch(STORE, tb)
    park = STORE.parks.get(tb["park_id"])
    # Cascade: CONFIRMED + NOT_CHECKED_IN tickets -> EXPIRED (no refund); release slot.
    for ticket in list(STORE.tickets.values()):
        if ticket["time_block_id"] != tid:
            continue
        if ticket["lifecycle_state"] == "CONFIRMED" and ticket["checkin_state"] == "NOT_CHECKED_IN":
            ticket["lifecycle_state"] = "EXPIRED"
            touch(STORE, ticket)
            domain.release_ticket_slot(STORE, ticket)
    if park:
        domain.reconcile_park(STORE, park)
    return success(serialize(tb), 200)


# ===========================================================================
# Weather
# ===========================================================================
@app.route("/parks/<pid>/weather-logs", methods=["POST"])
def create_weather_log(pid):
    caller = auth_for("POST", "/parks/{id}/weather-logs")
    require_roles(caller, {"ParkOperator"})
    park = park_or_404(pid)
    body = get_json()
    observed_at = as_datetime(body, "observed_at")
    snow = as_int(body, "snow_depth_cm", minimum=0)
    wind = as_int(body, "wind_kph", minimum=0)
    derived = domain.derive_posture(park, snow, wind)
    rec = make_record(STORE, "WeatherLog", {
        "park_id": pid,
        "observed_at": iso_z(observed_at),
        "snow_depth_cm": snow,
        "wind_kph": wind,
        "derived_posture": derived,
    })
    rec["_observed_dt"] = observed_at
    STORE.weather_logs[rec["id"]] = rec
    # Appending a reading increments the park's version by one (explicit side effect),
    # then recompute posture (which may cascade and add its own bookkeeping bumps).
    touch(STORE, park)
    domain.recompute_posture_after_weather(STORE, park)
    return success(serialize(rec), 201)


@app.route("/parks/<pid>/weather-logs", methods=["GET"])
def list_weather_logs(pid):
    caller = auth_for("GET", "/parks/{id}/weather-logs")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"})
    park_or_404(pid)
    rows = [w for w in STORE.weather_logs.values() if w["park_id"] == pid]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


# ===========================================================================
# Waivers
# ===========================================================================
@app.route("/waivers", methods=["POST"])
def create_waiver():
    caller = auth_for("POST", "/waivers")
    require_roles(caller, {"GuestPatron", "SafetyMarshal"})
    body = get_json()
    patron_id = as_str(body, "patron_id")
    park_id = as_str(body, "park_id")
    signed_at = as_datetime(body, "signed_at")
    guardian_name = as_str(body, "guardian_name", required=False, default=None)
    find_or_404(STORE.patrons, patron_id)
    find_or_404(STORE.parks, park_id)
    rec = make_record(STORE, "Waiver", {
        "patron_id": patron_id,
        "park_id": park_id,
        "signed_at": iso_z(signed_at),
        "guardian_name": guardian_name,
        "status": "ACTIVE",
    })
    STORE.waivers[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/waivers", methods=["GET"])
def list_waivers():
    caller = auth_for("GET", "/waivers")
    require_roles(caller, {"GuestPatron", "SafetyMarshal", "ParkOperator"})
    rows = list(STORE.waivers.values())
    patron_id = request.args.get("patron_id")
    park_id = request.args.get("park_id")
    if patron_id is not None:
        rows = [w for w in rows if w["patron_id"] == patron_id]
    if park_id is not None:
        rows = [w for w in rows if w["park_id"] == park_id]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/waivers/<wid>", methods=["GET"])
def get_waiver(wid):
    caller = auth_for("GET", "/waivers/{id}")
    require_roles(caller, {"GuestPatron", "SafetyMarshal", "ParkOperator"})
    rec = find_or_404(STORE.waivers, wid)
    return success(serialize(rec), 200)


@app.route("/waivers/<wid>/revoke", methods=["POST"])
def revoke_waiver(wid):
    caller = auth_for("POST", "/waivers/{id}/revoke")
    require_roles(caller, {"SafetyMarshal"})
    rec = find_or_404(STORE.waivers, wid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Waiver must be ACTIVE to revoke.")
    rec["status"] = "REVOKED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


def has_active_waiver(patron_id, park_id):
    return any(
        w["patron_id"] == patron_id and w["park_id"] == park_id and w["status"] == "ACTIVE"
        for w in STORE.waivers.values()
    )


def active_waiver_for(patron_id, park_id):
    for w in STORE.waivers.values():
        if w["patron_id"] == patron_id and w["park_id"] == park_id and w["status"] == "ACTIVE":
            return w
    return None


# ===========================================================================
# Season passes
# ===========================================================================
@app.route("/season-passes", methods=["POST"])
def create_season_pass():
    caller = auth_for("POST", "/season-passes")
    require_roles(caller, {"ParkOperator", "GuestPatron"})
    body = get_json()
    park_id = as_str(body, "park_id")
    holder = as_str(body, "holder_patron_id")
    tier = as_enum(body, "tier", {"SILVER", "GOLD", "RESIDENT_GOLD"})
    valid_from = as_datetime(body, "valid_from")
    valid_until = as_datetime(body, "valid_until")
    find_or_404(STORE.parks, park_id)
    find_or_404(STORE.patrons, holder)
    if valid_until <= valid_from:
        raise ApiError("ERR_INVALID_REQUEST", 422, "valid_until must be strictly after valid_from.")
    rec = make_record(STORE, "SeasonPass", {
        "park_id": park_id,
        "holder_patron_id": holder,
        "tier": tier,
        "valid_from": iso_z(valid_from),
        "valid_until": iso_z(valid_until),
        "redemptions_today_count": 0,
        "status": "ACTIVE",
    })
    rec["_valid_from_dt"] = valid_from
    rec["_valid_until_dt"] = valid_until
    STORE.season_passes[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/season-passes", methods=["GET"])
def list_season_passes():
    caller = auth_for("GET", "/season-passes")
    require_roles(caller, {"GuestPatron", "ParkOperator"})
    rows = list(STORE.season_passes.values())
    holder = request.args.get("holder_patron_id")
    park_id = request.args.get("park_id")
    if holder is not None:
        rows = [p for p in rows if p["holder_patron_id"] == holder]
    if park_id is not None:
        rows = [p for p in rows if p["park_id"] == park_id]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/season-passes/<sid>", methods=["GET"])
def get_season_pass(sid):
    caller = auth_for("GET", "/season-passes/{id}")
    require_roles(caller, {"GuestPatron", "ParkOperator"})
    rec = find_or_404(STORE.season_passes, sid)
    return success(serialize(rec), 200)


@app.route("/season-passes/<sid>/suspend", methods=["POST"])
def suspend_season_pass(sid):
    caller = auth_for("POST", "/season-passes/{id}/suspend")
    require_roles(caller, {"ParkOperator"})
    rec = find_or_404(STORE.season_passes, sid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Season pass must be ACTIVE to suspend.")
    rec["status"] = "SUSPENDED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


# ===========================================================================
# Tickets
# ===========================================================================
@app.route("/tickets", methods=["POST"])
def create_ticket():
    caller = auth_for("POST", "/tickets")
    require_roles(caller, {"GuestPatron"})
    body = get_json()
    park_id = as_str(body, "park_id")
    time_block_id = as_str(body, "time_block_id")
    holder = as_str(body, "holder_patron_id")
    rider_height = as_int(body, "rider_height_cm", minimum=30)
    rider_age = as_int(body, "rider_age_years", minimum=0)
    season_pass_id = as_str(body, "season_pass_id", required=False, default=None)
    upgraded_from = as_str(body, "upgraded_from_ticket_id", required=False, default=None)

    # Existence (left-to-right): park, time block, holder, then optional FKs.
    park = find_or_404(STORE.parks, park_id)
    find_or_404(STORE.time_blocks, time_block_id)
    patron = find_or_404(STORE.patrons, holder)
    season_pass = None
    if season_pass_id is not None:
        season_pass = find_or_404(STORE.season_passes, season_pass_id)
    if upgraded_from is not None:
        find_or_404(STORE.tickets, upgraded_from)

    # Pass guards (only when season_pass_id set). Order per validations: daily-limit (14)
    # then validity (15)? PRD §3.3 lists validity first ("First ... Second ...").
    if season_pass is not None:
        # Validity: status ACTIVE and clock within [valid_from, valid_until).
        now = STORE.clock.now
        valid = (
            season_pass["status"] == "ACTIVE"
            and season_pass["_valid_from_dt"] <= now < season_pass["_valid_until_dt"]
        )
        if not valid:
            raise ApiError("ERR_PASS_NOT_VALID", 409, "Season pass is not valid.")
        allowance = domain.PASS_DAILY_ALLOWANCE[season_pass["tier"]]
        if season_pass["redemptions_today_count"] + 1 > allowance:
            raise ApiError("ERR_PASS_DAILY_LIMIT", 409, "Daily redemption allowance exceeded.")

    is_resident = domain.compute_is_resident(park, patron)
    base_price = domain.compute_ticket_price(rider_age, is_resident, season_pass)

    rec = make_record(STORE, "SessionTicket", {
        "park_id": park_id,
        "time_block_id": time_block_id,
        "holder_patron_id": holder,
        "season_pass_id": season_pass_id,
        "upgraded_from_ticket_id": upgraded_from,
        "rider_height_cm": rider_height,
        "rider_age_years": rider_age,
        "is_resident": is_resident,
        "base_price_cents": base_price,
        "lifecycle_state": "RESERVED",
        "checkin_state": "NOT_CHECKED_IN",
    })
    STORE.tickets[rec["id"]] = rec
    if season_pass is not None:
        season_pass["redemptions_today_count"] += 1
        touch(STORE, season_pass)
    return success(serialize(rec), 201)


@app.route("/tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    caller = auth_for("GET", "/tickets/{id}")
    require_roles(caller, {"GuestPatron", "SafetyMarshal", "ParkOperator"})
    rec = find_or_404(STORE.tickets, tid)
    return success(serialize(rec), 200)


@app.route("/tickets", methods=["GET"])
def list_tickets():
    caller = auth_for("GET", "/tickets")
    require_roles(caller, {"GuestPatron", "SafetyMarshal", "ParkOperator"})
    rows = list(STORE.tickets.values())
    for field in ("holder_patron_id", "park_id", "time_block_id",
                  "season_pass_id", "upgraded_from_ticket_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [t for t in rows if t.get(field) == val]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


def _check_ticket_owner(caller, ticket):
    if caller.role == "GuestPatron" and ticket["holder_patron_id"] != caller.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the ticket holder.")


@app.route("/tickets/<tid>/confirm", methods=["POST"])
def confirm_ticket(tid):
    caller = auth_for("POST", "/tickets/{id}/confirm")
    require_roles(caller, {"GuestPatron"})
    ticket = find_or_404(STORE.tickets, tid)
    _check_ticket_owner(caller, ticket)
    body = get_json()
    # State (5)
    if ticket["lifecycle_state"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket must be RESERVED to confirm.")
    tb = STORE.time_blocks.get(ticket["time_block_id"])
    park = STORE.parks.get(ticket["park_id"])
    # OCC (6)
    expected = as_int(body, "expected_time_block_version", required=True)
    if tb is None or expected != tb["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale time block version.")
    # Closed-park gate (7)
    if park and park["operational_posture"] == "CLOSED":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park is CLOSED.")
    # Confirm additionally requires posture exactly OPEN (RESTRICTED blocks too).
    if park and park["operational_posture"] != "OPEN":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park posture not OPEN.")
    # Waiver presence (8)
    if not has_active_waiver(ticket["holder_patron_id"], ticket["park_id"]):
        raise ApiError("ERR_WAIVER_MISSING", 409, "No active waiver for holder at park.")
    # Guardian for minors (9)
    if ticket["rider_age_years"] < 18:
        waiver = active_waiver_for(ticket["holder_patron_id"], ticket["park_id"])
        if waiver is None or not waiver.get("guardian_name"):
            raise ApiError("ERR_GUARDIAN_REQUIRED", 422, "Minor requires guardian on waiver.")
    # Capacity guard (16)
    cap_sum = domain.open_lane_capacity_sum(STORE, ticket["park_id"])
    if tb["committed_rider_count"] + 1 > cap_sum:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "Capacity exceeded.")
    # Commit
    ticket["lifecycle_state"] = "CONFIRMED"
    touch(STORE, ticket)
    tb["committed_rider_count"] += 1
    touch(STORE, tb)  # this is the version bump that fails stale followers
    if park:
        domain.recompute_park_remaining(STORE, park)
    return success(serialize(ticket), 200)


@app.route("/tickets/<tid>/refund", methods=["POST"])
def refund_ticket(tid):
    caller = auth_for("POST", "/tickets/{id}/refund")
    require_roles(caller, {"GuestPatron"})
    ticket = find_or_404(STORE.tickets, tid)
    _check_ticket_owner(caller, ticket)
    if ticket["lifecycle_state"] != "CONFIRMED" or ticket["checkin_state"] != "NOT_CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not refundable in current state.")
    ticket["lifecycle_state"] = "REFUNDED"
    touch(STORE, ticket)
    domain.release_ticket_slot(STORE, ticket)
    domain.create_refund_entry(STORE, ticket["id"], None, ticket["base_price_cents"], "PATRON_CANCEL")
    if ticket.get("season_pass_id"):
        sp = STORE.season_passes.get(ticket["season_pass_id"])
        if sp is not None and sp["redemptions_today_count"] > 0:
            sp["redemptions_today_count"] -= 1
            touch(STORE, sp)
    return success(serialize(ticket), 200)


@app.route("/tickets/<tid>/gear-up", methods=["POST"])
def gear_up_ticket(tid):
    caller = auth_for("POST", "/tickets/{id}/gear-up")
    require_roles(caller, {"SafetyMarshal"})
    ticket = find_or_404(STORE.tickets, tid)
    if ticket["checkin_state"] != "NOT_CHECKED_IN" or ticket["lifecycle_state"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not gear-up-able in current state.")
    has_tube = any(
        r["ticket_id"] == tid and r["equipment_type"] == "TUBE" and r["state"] == "DISPATCHED"
        for r in STORE.equipment_rentals.values()
    )
    if not has_tube:
        raise ApiError("ERR_INVALID_STATE", 409, "No dispatched TUBE for this ticket.")
    # Height minimum for TUBE.
    if ticket["rider_height_cm"] < domain.MIN_TUBE_HEIGHT_CM:
        raise ApiError("ERR_HEIGHT_BELOW_MIN", 422, "Rider below minimum tube height.")
    ticket["checkin_state"] = "GEARED_UP"
    touch(STORE, ticket)
    return success(serialize(ticket), 200)


@app.route("/tickets/<tid>/board", methods=["POST"])
def board_ticket(tid):
    caller = auth_for("POST", "/tickets/{id}/board")
    require_roles(caller, {"SafetyMarshal"})
    ticket = find_or_404(STORE.tickets, tid)
    body = get_json()
    lane_id = as_str(body, "lane_id")
    boarded_at = as_datetime(body, "boarded_at")
    lane = find_or_404(STORE.lanes, lane_id)
    # State (5)
    if ticket["checkin_state"] != "GEARED_UP":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket must be GEARED_UP to board.")
    park = STORE.parks.get(ticket["park_id"])
    # Closed-park gate (7)
    if park and park["operational_posture"] == "CLOSED":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park is CLOSED.")
    # Waiver (8)
    if not has_active_waiver(ticket["holder_patron_id"], ticket["park_id"]):
        raise ApiError("ERR_WAIVER_MISSING", 409, "No active waiver for holder at park.")
    # Lane must be OPEN.
    if lane["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Target lane is not OPEN.")
    # Lane-turn overlap (11): half-open [boarded_at, cleared_at) vs existing BOARDED turns.
    from datetime import timedelta
    cleared_at = boarded_at + timedelta(seconds=lane["conveyor_cycle_seconds"])
    for turn in STORE.conveyor_turns.values():
        if turn["lane_id"] != lane_id or turn["state"] != "BOARDED":
            continue
        ex_start = turn["_boarded_dt"]
        ex_end = turn["_cleared_dt"]
        # Overlap when intervals intersect (half-open, adjacency allowed).
        if boarded_at < ex_end and ex_start < cleared_at:
            raise ApiError("ERR_LANE_TURN_OVERLAP", 409, "Conveyor turn overlaps existing turn.")
    # Advance checkin + create conveyor turn.
    ticket["checkin_state"] = "ON_LANE"
    touch(STORE, ticket)
    turn = make_record(STORE, "ConveyorTurn", {
        "lane_id": lane_id,
        "time_block_id": ticket["time_block_id"],
        "ticket_id": tid,
        "boarded_at": iso_z(boarded_at),
        "cleared_at": iso_z(cleared_at),
        "state": "BOARDED",
    })
    turn["_boarded_dt"] = boarded_at
    turn["_cleared_dt"] = cleared_at
    STORE.conveyor_turns[turn["id"]] = turn
    return success(serialize(ticket), 200)


@app.route("/tickets/<tid>/redeem", methods=["POST"])
def redeem_ticket(tid):
    caller = auth_for("POST", "/tickets/{id}/redeem")
    require_roles(caller, {"SafetyMarshal"})
    ticket = find_or_404(STORE.tickets, tid)
    if ticket["lifecycle_state"] != "CONFIRMED" or ticket["checkin_state"] != "ON_LANE":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not redeemable in current state.")
    tb = STORE.time_blocks.get(ticket["time_block_id"])
    if tb is None or tb["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket's time block is not ACTIVE.")
    ticket["lifecycle_state"] = "REDEEMED"
    touch(STORE, ticket)
    return success(serialize(ticket), 200)


# ===========================================================================
# Equipment rentals
# ===========================================================================
@app.route("/equipment-rentals", methods=["POST"])
def create_equipment_rental():
    caller = auth_for("POST", "/equipment-rentals")
    require_roles(caller, {"SafetyMarshal"})
    body = get_json()
    ticket_id = as_str(body, "ticket_id")
    equipment_type = as_enum(body, "equipment_type", {"TUBE", "HELMET", "BOOTS"})
    tube_size = as_enum(body, "tube_size", {"SMALL", "MEDIUM", "LARGE"}, required=False, default=None)
    find_or_404(STORE.tickets, ticket_id)
    rec = make_record(STORE, "EquipmentRental", {
        "ticket_id": ticket_id,
        "equipment_type": equipment_type,
        "tube_size": tube_size,
        "state": "DISPATCHED",
    })
    STORE.equipment_rentals[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/equipment-rentals", methods=["GET"])
def list_equipment_rentals():
    caller = auth_for("GET", "/equipment-rentals")
    require_roles(caller, {"SafetyMarshal", "ParkOperator", "GuestPatron"})
    rows = list(STORE.equipment_rentals.values())
    ticket_id = request.args.get("ticket_id")
    if ticket_id is not None:
        rows = [r for r in rows if r["ticket_id"] == ticket_id]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/equipment-rentals/<rid>", methods=["GET"])
def get_equipment_rental(rid):
    caller = auth_for("GET", "/equipment-rentals/{id}")
    require_roles(caller, {"SafetyMarshal", "ParkOperator", "GuestPatron"})
    rec = find_or_404(STORE.equipment_rentals, rid)
    return success(serialize(rec), 200)


@app.route("/equipment-rentals/<rid>/return", methods=["POST"])
def return_equipment_rental(rid):
    caller = auth_for("POST", "/equipment-rentals/{id}/return")
    require_roles(caller, {"SafetyMarshal"})
    rec = find_or_404(STORE.equipment_rentals, rid)
    if rec["state"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Rental must be DISPATCHED to return.")
    rec["state"] = "RETURNED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


@app.route("/equipment-rentals/<rid>/report-damage", methods=["POST"])
def report_damage_equipment_rental(rid):
    caller = auth_for("POST", "/equipment-rentals/{id}/report-damage")
    require_roles(caller, {"SafetyMarshal"})
    rec = find_or_404(STORE.equipment_rentals, rid)
    if rec["state"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Rental must be DISPATCHED to report damage.")
    rec["state"] = "DAMAGED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


# ===========================================================================
# Conveyor turns
# ===========================================================================
@app.route("/conveyor-turns", methods=["GET"])
def list_conveyor_turns():
    caller = auth_for("GET", "/conveyor-turns")
    require_roles(caller, {"ParkOperator", "SafetyMarshal"})
    rows = list(STORE.conveyor_turns.values())
    for field in ("lane_id", "time_block_id", "ticket_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [t for t in rows if t.get(field) == val]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/conveyor-turns/<cid>", methods=["GET"])
def get_conveyor_turn(cid):
    caller = auth_for("GET", "/conveyor-turns/{id}")
    require_roles(caller, {"ParkOperator", "SafetyMarshal"})
    rec = find_or_404(STORE.conveyor_turns, cid)
    return success(serialize(rec), 200)


@app.route("/conveyor-turns/<cid>/clear", methods=["POST"])
def clear_conveyor_turn(cid):
    caller = auth_for("POST", "/conveyor-turns/{id}/clear")
    require_roles(caller, {"ParkOperator"})
    rec = find_or_404(STORE.conveyor_turns, cid)
    if rec["state"] != "BOARDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Turn must be BOARDED to clear.")
    if STORE.clock.now < rec["_cleared_dt"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Conveyor cycle has not yet elapsed.")
    rec["state"] = "CLEARED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


# ===========================================================================
# Group reservations
# ===========================================================================
@app.route("/group-reservations", methods=["POST"])
def create_group_reservation():
    caller = auth_for("POST", "/group-reservations")
    require_roles(caller, {"GroupHost"})
    body = get_json()
    park_id = as_str(body, "park_id")
    host = as_str(body, "host_patron_id")
    time_block_id = as_str(body, "time_block_id")
    rental_type = as_enum(body, "rental_type", {"SHARED_SEATS", "EXCLUSIVE_LANE"})
    party_size = as_int(body, "party_size", minimum=2)
    lane_id = as_str(body, "lane_id", required=False, default=None)
    # Existence
    find_or_404(STORE.parks, park_id)
    find_or_404(STORE.patrons, host)
    find_or_404(STORE.time_blocks, time_block_id)
    if lane_id is not None:
        find_or_404(STORE.lanes, lane_id)
    # EXCLUSIVE_LANE requires lane_id; SHARED_SEATS must not carry one.
    if rental_type == "EXCLUSIVE_LANE" and lane_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "EXCLUSIVE_LANE requires lane_id.")
    if rental_type == "SHARED_SEATS" and lane_id is not None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "SHARED_SEATS must not carry lane_id.")
    rec = make_record(STORE, "GroupReservation", {
        "park_id": park_id,
        "host_patron_id": host,
        "time_block_id": time_block_id,
        "lane_id": lane_id,
        "rental_type": rental_type,
        "party_size": party_size,
        "deposit_cents": 0,
        "state": "DRAFT",
    })
    STORE.group_reservations[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/group-reservations", methods=["GET"])
def list_group_reservations():
    caller = auth_for("GET", "/group-reservations")
    require_roles(caller, {"GroupHost", "ParkOperator"})
    rows = list(STORE.group_reservations.values())
    for field in ("host_patron_id", "park_id", "time_block_id", "lane_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/group-reservations/<gid>", methods=["GET"])
def get_group_reservation(gid):
    caller = auth_for("GET", "/group-reservations/{id}")
    require_roles(caller, {"GroupHost", "ParkOperator"})
    rec = find_or_404(STORE.group_reservations, gid)
    return success(serialize(rec), 200)


def _check_group_owner(caller, res):
    if caller.role == "GroupHost" and res["host_patron_id"] != caller.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the reservation host.")


@app.route("/group-reservations/<gid>/hold", methods=["POST"])
def hold_group_reservation(gid):
    caller = auth_for("POST", "/group-reservations/{id}/hold")
    require_roles(caller, {"GroupHost"})
    res = find_or_404(STORE.group_reservations, gid)
    _check_group_owner(caller, res)
    body = get_json()
    # State (5)
    if res["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be DRAFT to hold.")
    tb = STORE.time_blocks.get(res["time_block_id"])
    park = STORE.parks.get(res["park_id"])
    # OCC (6)
    expected = as_int(body, "expected_time_block_version", required=True)
    if tb is None or expected != tb["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale time block version.")
    # Closed-park gate (7) + hold requires posture exactly OPEN.
    if park and park["operational_posture"] == "CLOSED":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park is CLOSED.")
    if park and park["operational_posture"] != "OPEN":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park posture not OPEN.")
    if res["rental_type"] == "EXCLUSIVE_LANE":
        lane = STORE.lanes.get(res["lane_id"])
        # Lane availability (13): not CLOSED and not held by another group in same block.
        if lane is None or lane["status"] != "OPEN":
            raise ApiError("ERR_LANE_UNAVAILABLE", 409, "Target lane unavailable.")
        for other in STORE.group_reservations.values():
            if (other["id"] != gid and other["lane_id"] == res["lane_id"]
                    and other["time_block_id"] == res["time_block_id"]
                    and other["state"] == "HELD"):
                raise ApiError("ERR_LANE_UNAVAILABLE", 409, "Lane held by another group.")
    else:
        # SHARED_SEATS capacity guard (16).
        cap_sum = domain.open_lane_capacity_sum(STORE, res["park_id"])
        if tb["committed_rider_count"] + res["party_size"] > cap_sum:
            raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "Capacity exceeded.")
    # Commit hold.
    res["state"] = "HELD"
    res["deposit_cents"] = domain.compute_group_deposit(res["party_size"], res["rental_type"])
    touch(STORE, res)
    if res["rental_type"] == "EXCLUSIVE_LANE":
        lane = STORE.lanes.get(res["lane_id"])
        lane["status"] = "CLOSED"
        lane["closure_reason"] = "GROUP_RENTAL"
        touch(STORE, lane)
        if park:
            domain.reconcile_park(STORE, park)
    # Hold bumps the block version by one (OCC).
    touch(STORE, tb)
    if park:
        domain.recompute_park_remaining(STORE, park)
    return success(serialize(res), 200)


@app.route("/group-reservations/<gid>/revise", methods=["POST"])
def revise_group_reservation(gid):
    caller = auth_for("POST", "/group-reservations/{id}/revise")
    require_roles(caller, {"GroupHost"})
    res = find_or_404(STORE.group_reservations, gid)
    _check_group_owner(caller, res)
    if res["state"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be HELD to revise.")
    res["state"] = "DRAFT"
    touch(STORE, res)
    park = STORE.parks.get(res["park_id"])
    if res["rental_type"] == "EXCLUSIVE_LANE":
        lane = STORE.lanes.get(res["lane_id"])
        if lane is not None:
            lane["status"] = "OPEN"
            lane["closure_reason"] = None
            touch(STORE, lane)
        if park:
            domain.reconcile_park(STORE, park)
    return success(serialize(res), 200)


@app.route("/group-reservations/<gid>/confirm", methods=["POST"])
def confirm_group_reservation(gid):
    caller = auth_for("POST", "/group-reservations/{id}/confirm")
    require_roles(caller, {"GroupHost"})
    res = find_or_404(STORE.group_reservations, gid)
    _check_group_owner(caller, res)
    if res["state"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be HELD to confirm.")
    park = STORE.parks.get(res["park_id"])
    # Closed-park gate (7) — group confirm is gated only on CLOSED, but PRD §3.7 says
    # confirm requires posture exactly OPEN.
    if park and park["operational_posture"] == "CLOSED":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park is CLOSED.")
    if park and park["operational_posture"] != "OPEN":
        raise ApiError("ERR_PARK_CLOSED", 409, "Park posture not OPEN.")
    tb = STORE.time_blocks.get(res["time_block_id"])
    if res["rental_type"] == "SHARED_SEATS":
        cap_sum = domain.open_lane_capacity_sum(STORE, res["park_id"])
        if tb["committed_rider_count"] + res["party_size"] > cap_sum:
            raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "Capacity exceeded.")
    res["state"] = "CONFIRMED"
    touch(STORE, res)
    if res["rental_type"] == "SHARED_SEATS":
        tb["committed_rider_count"] += res["party_size"]
        touch(STORE, tb)
        if park:
            domain.recompute_park_remaining(STORE, park)
    return success(serialize(res), 200)


@app.route("/group-reservations/<gid>/cancel", methods=["POST"])
def cancel_group_reservation(gid):
    caller = auth_for("POST", "/group-reservations/{id}/cancel")
    require_roles(caller, {"GroupHost"})
    res = find_or_404(STORE.group_reservations, gid)
    _check_group_owner(caller, res)
    if res["state"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be HELD or CONFIRMED to cancel.")
    prev_state = res["state"]
    park = STORE.parks.get(res["park_id"])
    tb = STORE.time_blocks.get(res["time_block_id"])
    res["state"] = "CANCELLED"
    touch(STORE, res)
    if res["rental_type"] == "SHARED_SEATS" and prev_state == "CONFIRMED":
        if tb is not None and tb["committed_rider_count"] >= res["party_size"]:
            tb["committed_rider_count"] -= res["party_size"]
            touch(STORE, tb)
        if park:
            domain.recompute_park_remaining(STORE, park)
    if res["rental_type"] == "EXCLUSIVE_LANE":
        lane = STORE.lanes.get(res["lane_id"])
        if lane is not None and lane["status"] == "CLOSED" and lane["closure_reason"] == "GROUP_RENTAL":
            lane["status"] = "OPEN"
            lane["closure_reason"] = None
            touch(STORE, lane)
        if park:
            domain.reconcile_park(STORE, park)
    domain.create_refund_entry(STORE, None, res["id"], res["deposit_cents"], "GROUP_CANCEL")
    return success(serialize(res), 200)


# ===========================================================================
# Add-ons
# ===========================================================================
@app.route("/add-ons", methods=["POST"])
def create_add_on():
    caller = auth_for("POST", "/add-ons")
    require_roles(caller, {"GuestPatron", "SafetyMarshal"})
    body = get_json()
    park_id = as_str(body, "park_id")
    ticket_id = as_str(body, "ticket_id")
    category = as_enum(body, "category", {"FOOD", "RENTAL_UPGRADE", "HOT_DRINK"})
    unit_price = as_int(body, "unit_price_cents", minimum=0)
    quantity = as_int(body, "quantity", minimum=1)
    find_or_404(STORE.parks, park_id)
    ticket = find_or_404(STORE.tickets, ticket_id)
    line_total = domain.compute_addon_line_total(STORE, category, unit_price, quantity, ticket)
    rec = make_record(STORE, "AddOn", {
        "park_id": park_id,
        "ticket_id": ticket_id,
        "category": category,
        "unit_price_cents": unit_price,
        "quantity": quantity,
        "line_total_cents": line_total,
        "state": "ORDERED",
    })
    STORE.add_ons[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/add-ons", methods=["GET"])
def list_add_ons():
    caller = auth_for("GET", "/add-ons")
    require_roles(caller, {"GuestPatron", "SafetyMarshal", "ParkOperator"})
    rows = list(STORE.add_ons.values())
    for field in ("ticket_id", "park_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/add-ons/<aid>", methods=["GET"])
def get_add_on(aid):
    caller = auth_for("GET", "/add-ons/{id}")
    require_roles(caller, {"GuestPatron", "SafetyMarshal", "ParkOperator"})
    rec = find_or_404(STORE.add_ons, aid)
    return success(serialize(rec), 200)


@app.route("/add-ons/<aid>/fulfill", methods=["POST"])
def fulfill_add_on(aid):
    caller = auth_for("POST", "/add-ons/{id}/fulfill")
    require_roles(caller, {"SafetyMarshal"})
    rec = find_or_404(STORE.add_ons, aid)
    if rec["state"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Add-on must be ORDERED to fulfill.")
    rec["state"] = "FULFILLED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


@app.route("/add-ons/<aid>/void", methods=["POST"])
def void_add_on(aid):
    caller = auth_for("POST", "/add-ons/{id}/void")
    require_roles(caller, {"GuestPatron", "SafetyMarshal"})
    rec = find_or_404(STORE.add_ons, aid)
    if rec["state"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Add-on must be ORDERED to void.")
    rec["state"] = "VOIDED"
    touch(STORE, rec)
    return success(serialize(rec), 200)


# ===========================================================================
# Refund entries
# ===========================================================================
@app.route("/refund-entries", methods=["GET"])
def list_refund_entries():
    caller = auth_for("GET", "/refund-entries")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator"})
    rows = list(STORE.refund_entries.values())
    for field in ("ticket_id", "group_reservation_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, pagination=meta)


@app.route("/refund-entries/<rid>", methods=["GET"])
def get_refund_entry(rid):
    caller = auth_for("GET", "/refund-entries/{id}")
    require_roles(caller, {"GuestPatron", "GroupHost", "ParkOperator"})
    rec = find_or_404(STORE.refund_entries, rid)
    return success(serialize(rec), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = auth_for("POST", "/_clock/set_current_utc")
    require_roles(caller, {"ParkOperator"})
    body = get_json()
    to_iso = as_datetime(body, "to_iso8601")
    old = STORE.clock.now
    STORE.clock.set(to_iso)
    # Daily sweep: when the UTC calendar date advances, reset redemptions_today_count
    # to 0; and flip any pass (ACTIVE or SUSPENDED) whose valid_until <= new clock to EXPIRED.
    date_advanced = to_iso.date() > old.date()
    for sp in STORE.season_passes.values():
        if date_advanced and sp["redemptions_today_count"] != 0:
            sp["redemptions_today_count"] = 0
            touch(STORE, sp)
        if sp["status"] in ("ACTIVE", "SUSPENDED") and to_iso >= sp["_valid_until_dt"]:
            sp["status"] = "EXPIRED"
            touch(STORE, sp)
    return success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
