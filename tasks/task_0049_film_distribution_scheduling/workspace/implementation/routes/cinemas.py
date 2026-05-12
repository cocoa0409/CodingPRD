"""Cinema endpoints."""

from flask import Blueprint

from db import db, new_id
from clock import now_iso
from middleware import (
    require_roles,
    parse_json_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
)
from response import success_object
from errors import ERR_NOT_FOUND, raise_error

bp = Blueprint("cinemas", __name__)

TIERS = {"TIER_1", "TIER_2", "TIER_3"}


@bp.route("/cinemas", methods=["POST"])
@require_roles({"CinemaOps"})
def create_cinema():
    body = parse_json_body()
    require_fields(body, ["name", "region_code", "tier"])
    name = require_str(body.get("name"), "name")
    region_code = require_str(body.get("region_code"), "region_code")
    tier = require_enum(body.get("tier"), "tier", TIERS)
    peak_start = body.get("peak_window_start_minute", 1080)
    peak_end = body.get("peak_window_end_minute", 1380)
    peak_start = require_int(peak_start, "peak_window_start_minute", min_v=0, max_v=1439)
    peak_end = require_int(peak_end, "peak_window_end_minute", min_v=0, max_v=1439)
    now = now_iso()
    cinema = {
        "id": new_id(),
        "name": name,
        "region_code": region_code,
        "tier": tier,
        "peak_window_start_minute": peak_start,
        "peak_window_end_minute": peak_end,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.cinemas[cinema["id"]] = cinema
    return success_object(cinema, http_status=201)


@bp.route("/cinemas/<cinema_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def get_cinema(cinema_id):
    c = db.cinemas.get(cinema_id)
    if not c:
        raise_error(ERR_NOT_FOUND, "cinema not found")
    return success_object(c)
