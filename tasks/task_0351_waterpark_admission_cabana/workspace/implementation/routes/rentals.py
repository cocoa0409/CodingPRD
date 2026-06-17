"""CabanaRental and LockerRental endpoints (PRD §3.6, §3.7)."""
from flask import Blueprint, request

import errors
from db import db, new_id, add_common_fields, touch, now_iso
from errors import ApiError
from middleware import authenticate, require_role
from response import success, list_success
from services import serialize
from services.calculations import locker_charge
from services.common import (
    get_json_body, require_int, parse_pagination, paginate, parse_datetime,
)
from services.lookup import (
    get_cabana, get_order, get_entry_window, get_locker,
    get_cabana_rental, get_locker_rental, require_owner,
)

bp = Blueprint("rentals", __name__)


# ---- CabanaRental ----
@bp.route("/cabana-rentals", methods=["POST"])
def create_cabana_rental():
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    body = get_json_body()

    # Existence (priority 4), left-to-right: cabana, order, window.
    for field in ("cabana_id", "order_id", "entry_window_id"):
        if field not in body or body[field] is None:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"Missing required field: {field}")
    cabana = get_cabana(body["cabana_id"])
    order = get_order(body["order_id"])
    win = get_entry_window(body["entry_window_id"])

    # Ownership: guest acts on their own order.
    require_owner(role, user_id, order["guest_id"])

    # Schema (priority 5): timestamps and version.
    if "starts_at" not in body or body["starts_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: starts_at")
    if "ends_at" not in body or body["ends_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: ends_at")
    starts_dt = parse_datetime(body["starts_at"], "starts_at")
    ends_dt = parse_datetime(body["ends_at"], "ends_at")
    if not (starts_dt < ends_dt):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "starts_at must be strictly before ends_at")
    expected_version = require_int(body, "expected_entry_window_version")

    # OCC (priority 7) precedes business checks.
    if expected_version != win["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_entry_window_version does not match window version")

    park = db.parks[cabana["park_id"]]

    # PRD §3.6 prose order: capacity, then weather, then time-overlap.
    if win["reserved_count"] + win["admitted_count"] >= win["window_capacity"]:
        raise ApiError(errors.ERR_WINDOW_CAPACITY_EXCEEDED, 409,
                       "window capacity would be exceeded")
    if park["weather_status"] in {"STORM_WATCH", "RAINED_OUT"}:
        raise ApiError(errors.ERR_WEATHER_HOLD, 409,
                       "new cabana sales blocked by weather posture")

    # Time-overlap on the same cabana against non-terminal rentals (HELD/CONFIRMED),
    # expanding each existing rental on its END side by turnover_buffer_minutes.
    buffer_seconds = cabana["turnover_buffer_minutes"] * 60
    for cr in db.cabana_rentals.values():
        if cr["cabana_id"] != cabana["id"]:
            continue
        if cr["status"] not in {"HELD", "CONFIRMED"}:
            continue
        r_start = parse_datetime(cr["starts_at"], "starts_at")
        r_end = parse_datetime(cr["ends_at"], "ends_at")
        from datetime import timedelta
        buffered_end = r_end + timedelta(seconds=buffer_seconds)
        if starts_dt < buffered_end and ends_dt > r_start:
            raise ApiError(errors.ERR_CABANA_OVERLAP, 409,
                           "rental collides with a buffered prior rental on this cabana")

    rec = {
        "id": new_id(),
        "cabana_id": cabana["id"],
        "order_id": order["id"],
        "park_id": cabana["park_id"],
        "entry_window_id": win["id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "price_cents": cabana["daily_rate_cents"],
        "status": "HELD",
    }
    add_common_fields(rec)
    db.cabana_rentals[rec["id"]] = rec

    # Hold capacity on the named window: reserved_count++ and version++.
    win["reserved_count"] += 1
    touch(win)
    return success(serialize.cabana_rental(rec), status=201)


@bp.route("/cabana-rentals/<rid>", methods=["GET"])
def get_cabana_rental_route(rid):
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager", "FinanceClerk"})
    rec = get_cabana_rental(rid)
    return success(serialize.cabana_rental(rec))


@bp.route("/cabana-rentals", methods=["GET"])
def list_cabana_rentals():
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager", "FinanceClerk"})
    limit, offset = parse_pagination()
    rows = list(db.cabana_rentals.values())
    for key in ("park_id", "entry_window_id", "cabana_id", "order_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.cabana_rental(r) for r in page], limit, offset, total)


@bp.route("/cabanas/<cid>/cabana-rentals", methods=["GET"])
def list_cabana_rentals_for_cabana(cid):
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager"})
    cabana = get_cabana(cid)
    limit, offset = parse_pagination()
    rows = [r for r in db.cabana_rentals.values() if r["cabana_id"] == cabana["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.cabana_rental(r) for r in page], limit, offset, total)


@bp.route("/cabana-rentals/<rid>/cancel", methods=["POST"])
def cancel_cabana_rental(rid):
    user_id, role = authenticate()
    require_role(role, {"Guest", "ParkManager"})
    rec = get_cabana_rental(rid)
    order = db.orders.get(rec["order_id"])
    require_owner(role, user_id, order["guest_id"] if order else None)

    if rec["status"] not in {"HELD", "CONFIRMED"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "cancel requires cabana rental status HELD or CONFIRMED")
    rec["status"] = "CANCELLED"
    touch(rec)
    win = db.entry_windows.get(rec["entry_window_id"])
    if win is not None and win["reserved_count"] > 0:
        win["reserved_count"] -= 1
        touch(win)
    return success(serialize.cabana_rental(rec))


# ---- LockerRental ----
@bp.route("/locker-rentals", methods=["POST"])
def create_locker_rental():
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    body = get_json_body()

    for field in ("locker_id", "order_id"):
        if field not in body or body[field] is None:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"Missing required field: {field}")
    locker = get_locker(body["locker_id"])
    order = get_order(body["order_id"])
    require_owner(role, user_id, order["guest_id"])

    if "starts_at" not in body or body["starts_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: starts_at")
    if "ends_at" not in body or body["ends_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: ends_at")
    starts_dt = parse_datetime(body["starts_at"], "starts_at")
    ends_dt = parse_datetime(body["ends_at"], "ends_at")
    if not (starts_dt < ends_dt):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "starts_at must be strictly before ends_at")

    hours_billed, price_cents = locker_charge(starts_dt, ends_dt, locker["hourly_rate_cents"])

    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "locker_id": locker["id"],
        "order_id": order["id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "hours_billed": hours_billed,
        "price_cents": price_cents,
    }
    db.locker_rentals[rec["id"]] = rec
    return success(serialize.locker_rental(rec), status=201)


@bp.route("/locker-rentals/<rid>", methods=["GET"])
def get_locker_rental_route(rid):
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager", "FinanceClerk"})
    rec = get_locker_rental(rid)
    return success(serialize.locker_rental(rec))


@bp.route("/lockers/<lid>/locker-rentals", methods=["GET"])
def list_locker_rentals_for_locker(lid):
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager"})
    locker = get_locker(lid)
    limit, offset = parse_pagination()
    rows = [r for r in db.locker_rentals.values() if r["locker_id"] == locker["id"]]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.locker_rental(r) for r in page], limit, offset, total)
