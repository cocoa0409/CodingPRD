"""Screen endpoints."""

from flask import Blueprint

from db import db, new_id
from clock import now_iso
from middleware import (
    require_roles,
    parse_json_body,
    require_fields,
    require_int,
    require_str,
)
from response import success_object
from errors import ERR_NOT_FOUND, ERR_BAD_REQUEST, raise_error

bp = Blueprint("screens", __name__)


FORMATS = {"2D", "3D", "IMAX"}


@bp.route("/cinemas/<cinema_id>/screens", methods=["POST"])
@require_roles({"CinemaOps"})
def create_screen(cinema_id):
    # Path existence
    cinema = db.cinemas.get(cinema_id)
    if not cinema:
        raise_error(ERR_NOT_FOUND, "cinema not found")
    body = parse_json_body()
    require_fields(body, ["label", "supported_formats", "operating_start_minute", "operating_end_minute", "seat_capacity"])
    label = require_str(body.get("label"), "label")
    supported_formats = body.get("supported_formats")
    if not isinstance(supported_formats, list) or not supported_formats:
        raise_error(ERR_BAD_REQUEST, "supported_formats must be non-empty array")
    for f in supported_formats:
        if f not in FORMATS:
            raise_error(ERR_BAD_REQUEST, f"unknown format {f}")
    op_start = require_int(body.get("operating_start_minute"), "operating_start_minute", min_v=0, max_v=1439)
    op_end = require_int(body.get("operating_end_minute"), "operating_end_minute", min_v=1, max_v=1440)
    if op_end <= op_start:
        raise_error(ERR_BAD_REQUEST, "operating_end_minute must be > operating_start_minute")
    cleaning = body.get("cleaning_interval_minutes", 15)
    trailer = body.get("trailer_minutes", 10)
    ad = body.get("ad_minutes", 5)
    cleaning = require_int(cleaning, "cleaning_interval_minutes", min_v=0)
    trailer = require_int(trailer, "trailer_minutes", min_v=0)
    ad = require_int(ad, "ad_minutes", min_v=0)
    seat_capacity = require_int(body.get("seat_capacity"), "seat_capacity", min_v=1)

    now = now_iso()
    screen = {
        "id": new_id(),
        "cinema_id": cinema_id,
        "label": label,
        "supported_formats": list(supported_formats),
        "operating_start_minute": op_start,
        "operating_end_minute": op_end,
        "cleaning_interval_minutes": cleaning,
        "trailer_minutes": trailer,
        "ad_minutes": ad,
        "seat_capacity": seat_capacity,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.screens[screen["id"]] = screen
    return success_object(screen, http_status=201)


@bp.route("/screens/<screen_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def get_screen(screen_id):
    s = db.screens.get(screen_id)
    if not s:
        raise_error(ERR_NOT_FOUND, "screen not found")
    return success_object(s)
