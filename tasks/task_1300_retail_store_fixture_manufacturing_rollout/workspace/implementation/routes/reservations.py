"""StagingReservation endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_WINDOW,
    ERR_KIT_CONFIG_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_RESERVATION_NOT_HELD,
    ERR_KIT_INVALID_STATE,
    ERR_STAGING_BAY_OVERLAP,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import staging_conflict
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("reservations", __name__)


def _get_reservation_or_404(reservation_id: str) -> dict:
    reservation = db.reservations.get(reservation_id)
    if reservation is None:
        raise_err(ERR_RESERVATION_NOT_FOUND, "StagingReservation id does not exist")
    return reservation


@bp.route("/staging-reservations", methods=["POST"])
@require_roles("WarehouseLead")
def create_reservation(_user_id: str, _role: str):
    body = get_json_body()
    kit_id = require_string(body, "kit_id")
    staging_bay_code = require_string(body, "staging_bay_code")
    start_ts = require_ts(body, "start_ts")
    end_ts = require_ts(body, "end_ts")

    # Body-FK existence
    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_CONFIG_NOT_FOUND, "StoreKitConfig id does not exist")

    # State: kit must be RELEASED
    if kit["status"] != "RELEASED":
        raise_err(ERR_KIT_INVALID_STATE, "reservation creation requires kit RELEASED")

    start_dt = parse_iso8601(start_ts, "start_ts")
    end_dt = parse_iso8601(end_ts, "end_ts")
    if not (end_dt > start_dt):
        raise_err(ERR_INVALID_WINDOW, "end_ts must be strictly after start_ts")

    # Temporal conflict: half-open overlap against HELD reservations on same bay
    if staging_conflict(staging_bay_code, start_dt, end_dt):
        raise_err(ERR_STAGING_BAY_OVERLAP, "Half-open staging window overlaps a HELD reservation on the same bay")

    reservation = {
        "kit_id": kit_id,
        "staging_bay_code": staging_bay_code,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "status": "HELD",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_new(reservation)
    db.reservations[reservation["id"]] = reservation
    return success_object(serialize(reservation), 201)


@bp.route("/staging-reservations", methods=["GET"])
@require_roles("Any")
def list_reservations(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.reservations.values()))
    items = apply_filters(items, ["kit_id", "staging_bay_code", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/staging-reservations/<reservation_id>", methods=["GET"])
@require_roles("Any")
def get_reservation(reservation_id: str, _user_id: str, _role: str):
    reservation = _get_reservation_or_404(reservation_id)
    return success_object(serialize(reservation))


@bp.route("/staging-reservations/<reservation_id>/release", methods=["POST"])
@require_roles("WarehouseLead")
def release_reservation(reservation_id: str, _user_id: str, _role: str):
    reservation = _get_reservation_or_404(reservation_id)
    if reservation["status"] != "HELD":
        raise_err(ERR_RESERVATION_NOT_HELD, "Reservation release requires status HELD")
    reservation["status"] = "RELEASED"
    db.touch(reservation)
    return success_object(serialize(reservation))
