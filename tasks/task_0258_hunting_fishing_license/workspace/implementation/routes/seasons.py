"""SpeciesSeason endpoints (PRD §3.4)."""
from flask import Blueprint, request

import serialize
from db import store, parse_dt
from errors import err, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_int, as_bool, parse_pagination, paginate,
)
from services.core import get_species_season_or_404

bp = Blueprint("seasons", __name__)


def _validate_iso(value, field):
    try:
        parse_dt(value)
    except Exception:
        raise err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 datetime")


@bp.route("/species-seasons", methods=["POST"])
@require_roles("DrawOfficer")
def create_species_season():
    body = get_json_body()
    species = as_nonempty_str(body, "species", required=True)
    season_open = as_nonempty_str(body, "season_open", required=True)
    season_close = as_nonempty_str(body, "season_close", required=True)
    bag_limit = as_int(body, "bag_limit", required=True, minimum=0)
    draw_required = as_bool(body, "draw_required", required=False, default=False)

    _validate_iso(season_open, "season_open")
    _validate_iso(season_close, "season_close")

    record = {
        "species": species,
        "season_open": season_open,
        "season_close": season_close,
        "bag_limit": bag_limit,
        "draw_required": draw_required,
        "status": "DRAFT",
    }
    store.stamp_new(record)
    store.species_seasons[record["id"]] = record
    return success(serialize.species_season(record), status=201, response_type="object")


@bp.route("/species-seasons/<id>", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "GameWarden", "Applicant")
def get_species_season(id):
    record = get_species_season_or_404(id)
    return success(serialize.species_season(record), status=200, response_type="object")


@bp.route("/species-seasons", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "GameWarden", "Applicant")
def list_species_seasons():
    limit, offset = parse_pagination()
    items = list(store.species_seasons.values())
    species = request.args.get("species")
    if species is not None:
        items = [r for r in items if r["species"] == species]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.species_season(r) for r in page], limit, offset, total
    )


@bp.route("/species-seasons/<id>/open", methods=["POST"])
@require_roles("DrawOfficer")
def open_species_season(id):
    record = get_species_season_or_404(id)
    if record["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Season is not DRAFT")
    record["status"] = "OPEN"
    store.touch(record)
    return success(serialize.species_season(record), status=200, response_type="object")


@bp.route("/species-seasons/<id>/close", methods=["POST"])
@require_roles("DrawOfficer")
def close_species_season(id):
    record = get_species_season_or_404(id)
    if record["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Season is not OPEN")
    record["status"] = "CLOSED"
    store.touch(record)
    return success(serialize.species_season(record), status=200, response_type="object")
