"""GpsTrack routes (append-only — id + created_at only, no version)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_GPS_BOOKING_NOT_IN_PROGRESS,
)
from middleware import require_auth
from services.common import (
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_iso8601,
    require_number,
    require_str,
    sorted_by_created_at,
)
from services.lookup import fk_booking, get_gps_track_or_404

bp = Blueprint("gps_tracks", __name__)


def gps_to_dict(g: dict) -> dict:
    return {
        "id": g["id"],
        "booking_id": g["booking_id"],
        "latitude": g["latitude"],
        "longitude": g["longitude"],
        "recorded_at": g["recorded_at"],
        "created_at": g["created_at"],
    }


@bp.post("/api/v1/gps-tracks")
@require_auth(roles=["Sitter"])
def create_gps():
    body = get_json_body()
    booking_id = require_str(body, "booking_id")
    latitude = require_number(body, "latitude")
    longitude = require_number(body, "longitude")
    recorded_dt = require_iso8601(body, "recorded_at")

    if latitude < -90 or latitude > 90:
        raise ApiError(ERR_INVALID_REQUEST, "latitude must be in [-90, 90].")
    if longitude < -180 or longitude > 180:
        raise ApiError(ERR_INVALID_REQUEST, "longitude must be in [-180, 180].")

    booking = fk_booking(booking_id)
    if booking["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_GPS_BOOKING_NOT_IN_PROGRESS,
            "Booking must be IN_PROGRESS to append GpsTrack.",
        )

    with db.lock:
        g = {
            **new_common_fields(with_version=False),
            "booking_id": booking_id,
            "latitude": latitude,
            "longitude": longitude,
            "recorded_at": db.fmt_ts(recorded_dt),
        }
        db.gps_tracks[g["id"]] = g
    return response.ok(gps_to_dict(g), status=201)


@bp.get("/api/v1/gps-tracks/<gid>")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def get_gps(gid: str):
    g = get_gps_track_or_404(gid)
    return response.ok(gps_to_dict(g))


@bp.get("/api/v1/gps-tracks")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def list_gps():
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")

    items = list(db.gps_tracks.values())
    if booking_id is not None:
        items = [g for g in items if g["booking_id"] == booking_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([gps_to_dict(g) for g in page], limit, offset, total)
