"""Laser Tag & Paintball Arena API — Flask entry point and all routes."""

import os

from flask import Flask, request

import db
from errors import ApiError, err
from middleware import require_auth, require_role, ALL_ROLES
from response import success, list_success, error_response
from serialize import serialize
from timeutil import EPOCH_ISO, parse_iso
from validation import (
    get_json_body,
    parse_pagination,
    require_string,
    require_int,
    optional_int,
    optional_number,
    optional_bool,
    require_enum,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    # Unknown route path — treat as a generic not-found shaped envelope.
    return error_response("ERR_VALIDATION", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_VALIDATION", "Method not allowed"), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_VALIDATION", f"Unexpected error: {e}"), 400


# ---------------------------------------------------------------------------
# Lookup helpers (existence, priority 3)
# ---------------------------------------------------------------------------

def get_arena(arena_id):
    a = db.arenas.get(arena_id)
    if a is None:
        raise err("ERR_ARENA_NOT_FOUND", "Arena not found")
    return a


def get_field(field_id):
    f = db.fields.get(field_id)
    if f is None:
        raise err("ERR_FIELD_NOT_FOUND", "Field not found")
    return f


def get_package(package_id):
    p = db.party_packages.get(package_id)
    if p is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Package not found")
    return p


def get_booking(booking_id):
    b = db.bookings.get(booking_id)
    if b is None:
        raise err("ERR_BOOKING_NOT_FOUND", "Booking not found")
    return b


def get_equipment(unit_id):
    u = db.equipment_units.get(unit_id)
    if u is None:
        raise err("ERR_EQUIPMENT_NOT_FOUND", "Equipment unit not found")
    return u


def get_rental(rental_id):
    r = db.rentals.get(rental_id)
    if r is None:
        raise err("ERR_RENTAL_NOT_FOUND", "Rental not found")
    return r


def get_waiver(waiver_id):
    w = db.waiver_profiles.get(waiver_id)
    if w is None:
        raise err("ERR_WAIVER_NOT_FOUND", "Waiver profile not found")
    return w


def get_referee(referee_id):
    r = db.referees.get(referee_id)
    if r is None:
        raise err("ERR_REFEREE_NOT_FOUND", "Referee not found")
    return r


def get_assignment(assignment_id):
    a = db.referee_assignments.get(assignment_id)
    if a is None:
        raise err("ERR_ASSIGNMENT_NOT_FOUND", "Referee assignment not found")
    return a


def get_league(league_id):
    lg = db.leagues.get(league_id)
    if lg is None:
        raise err("ERR_LEAGUE_NOT_FOUND", "League not found")
    return lg


def get_match(match_id):
    m = db.league_matches.get(match_id)
    if m is None:
        raise err("ERR_MATCH_NOT_FOUND", "League match not found")
    return m




# ---------------------------------------------------------------------------
# Generic list helper
# ---------------------------------------------------------------------------

def paginate_and_list(kind, collection, predicate=None):
    limit, offset = parse_pagination()
    rows = [r for r in collection.values() if (predicate is None or predicate(r))]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_success([serialize(kind, r) for r in page], limit, offset, total)


# ===========================================================================
# ARENA
# ===========================================================================

@app.route("/arenas", methods=["POST"])
def create_arena():
    _, role = require_auth()
    require_role(role, {"ArenaManager"})
    body = get_json_body()
    name = require_string(body, "name")
    marker_total = require_int(body, "marker_pool_total", minimum=0)
    vest_total = require_int(body, "vest_pool_total", minimum=0)
    timezone = body.get("timezone")
    if timezone is None:
        timezone = "UTC"
    elif not isinstance(timezone, str):
        raise err("ERR_VALIDATION", "timezone must be a string")

    with db.LOCK:
        rec = db.base_record()
        rec.update({
            "name": name,
            "timezone": timezone,
            "current_utc": EPOCH_ISO,
            "marker_pool_total": marker_total,
            "vest_pool_total": vest_total,
            "marker_available_count": 0,
            "vest_available_count": 0,
            "deposit_held_cents": 0,
            "deposit_refunded_cents": 0,
            "deposit_forfeited_cents": 0,
            "status": "OPEN",
        })
        db.arenas[rec["id"]] = rec
        return success(serialize("arena", rec), 201)


@app.route("/arenas/<arena_id>", methods=["GET"])
def get_arena_route(arena_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    a = get_arena(arena_id)
    return success(serialize("arena", a), 200)


@app.route("/arenas", methods=["GET"])
def list_arenas():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    return paginate_and_list("arena", db.arenas)


@app.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = require_auth()
    require_role(role, {"ArenaManager"})
    body = get_json_body()
    arena_id = require_string(body, "arena_id")
    to_iso = require_string(body, "to_iso8601")
    with db.LOCK:
        a = get_arena(arena_id)
        if parse_iso(to_iso) is None:
            raise err("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 timestamp")
        a["current_utc"] = to_iso
        db.touch(a)
        return success(serialize("arena", a), 200)


@app.route("/arenas/<arena_id>/close", methods=["POST"])
def close_arena(arena_id):
    _, role = require_auth()
    require_role(role, {"ArenaManager"})
    with db.LOCK:
        a = get_arena(arena_id)
        a["status"] = "CLOSED"
        db.touch(a)
        return success(serialize("arena", a), 200)


# ===========================================================================
# FIELD
# ===========================================================================

@app.route("/fields", methods=["POST"])
def create_field():
    _, role = require_auth()
    require_role(role, {"ArenaManager"})
    body = get_json_body()
    arena_id = require_string(body, "arena_id")
    with db.LOCK:
        get_arena(arena_id)
        name = require_string(body, "name")
        game_mode = require_enum(body, "game_mode", {"LASER_TAG", "PAINTBALL"})
        capacity_max = require_int(body, "capacity_max", minimum=1)
        turnaround = optional_int(body, "turnaround_minutes", default=0, minimum=0)
        rec = db.base_record()
        rec.update({
            "arena_id": arena_id,
            "name": name,
            "game_mode": game_mode,
            "capacity_max": capacity_max,
            "turnaround_minutes": turnaround,
            "reserved_headcount": 0,
            "status": "ACTIVE",
        })
        db.fields[rec["id"]] = rec
        return success(serialize("field", rec), 201)


@app.route("/fields/<field_id>", methods=["GET"])
def get_field_route(field_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    f = get_field(field_id)
    return success(serialize("field", f), 200)


@app.route("/fields", methods=["GET"])
def list_fields():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    arena_id = request.args.get("arena_id")
    pred = (lambda r: r["arena_id"] == arena_id) if arena_id else None
    return paginate_and_list("field", db.fields, pred)


@app.route("/fields/<field_id>/close", methods=["POST"])
def close_field(field_id):
    _, role = require_auth()
    require_role(role, {"ArenaManager"})
    with db.LOCK:
        f = get_field(field_id)
        f["status"] = "CLOSED"
        db.touch(f)
        return success(serialize("field", f), 200)


# ===========================================================================
# PARTY PACKAGE
# ===========================================================================

@app.route("/party-packages", methods=["POST"])
def create_package():
    _, role = require_auth()
    require_role(role, {"ArenaManager"})
    body = get_json_body()
    arena_id = require_string(body, "arena_id")
    with db.LOCK:
        get_arena(arena_id)
        name = require_string(body, "name")
        included_players = require_int(body, "included_players", minimum=1)
        extra_fee = require_int(body, "extra_player_fee_cents", minimum=0)
        base_fee = require_int(body, "base_fee_cents", minimum=0)
        included_ammo = optional_int(body, "included_ammo_balls", default=0, minimum=0)
        discount_pct = optional_number(body, "discount_pct", default=0,
                                       minimum=0, exclusive_max=1)
        active = optional_bool(body, "active", default=True)
        rec = db.base_record()
        rec.update({
            "arena_id": arena_id,
            "name": name,
            "included_players": included_players,
            "extra_player_fee_cents": extra_fee,
            "base_fee_cents": base_fee,
            "included_ammo_balls": included_ammo,
            "discount_pct": discount_pct,
            "active": active,
        })
        db.party_packages[rec["id"]] = rec
        return success(serialize("party_package", rec), 201)


@app.route("/party-packages/<package_id>", methods=["GET"])
def get_package_route(package_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    p = get_package(package_id)
    return success(serialize("party_package", p), 200)


@app.route("/party-packages", methods=["GET"])
def list_packages():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    arena_id = request.args.get("arena_id")
    pred = (lambda r: r["arena_id"] == arena_id) if arena_id else None
    return paginate_and_list("party_package", db.party_packages, pred)


import routes_ext  # noqa: E402

routes_ext.register(app)


if __name__ == "__main__":
    import errno
    import time as _time

    port = int(os.environ.get("PORT", "10000"))
    # threaded=True lets the runner's readiness probe (and any test request) be
    # answered without queueing behind an in-flight handler, so a freshly booted
    # server responds promptly even under the 8-round concurrent stability sweep.
    # All mutations are still serialized by db.LOCK, so threading is behaviourally
    # invisible. use_reloader=False avoids a second interpreter spawn per boot.
    #
    # Bind-retry loop: under per-test-server isolation the runner kills the
    # previous server and immediately re-launches this one on the SAME port
    # before every test. When the stability sweep runs all rounds in lockstep,
    # the just-killed predecessor's socket can still be in the kernel's release
    # path when this boot tries to bind, raising EADDRINUSE. Exiting here would
    # leave the runner polling a dead port for its entire 15s restart window
    # ("could not be restarted"). So retry the bind for a few seconds until the
    # port frees, then serve. This changes no API behaviour — it only makes the
    # boot resilient to rapid-restart contention.
    for _attempt in range(140):  # ~14s, just under the runner's 15s poll window
        try:
            app.run(
                host="0.0.0.0",
                port=port,
                threaded=True,
                use_reloader=False,
            )
            break  # app.run blocks until shutdown; only reached on clean stop
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                raise
            _time.sleep(0.1)
    else:
        # Port never freed within the window; make the failure explicit.
        app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
