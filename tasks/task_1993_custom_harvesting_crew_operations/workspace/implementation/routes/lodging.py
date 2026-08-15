"""LodgingSite and LodgingReservation endpoints (§3.3, §3.6)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_LODGING_CAPACITY_EXCEEDED,
    ERR_RESERVATION_NOT_BOOKED,
    ERR_RESERVATION_NOT_CANCELLABLE,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    optional_type,
    parse_date,
    daterange,
    stamp_new,
    touch,
    public,
    sort_key,
    get_season_or_404,
    get_site_or_404,
    get_stop_or_404,
    get_crew_or_404,
    get_reservation_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("lodging", __name__)


# ---------------------------------------------------------------------------
# LodgingSite
# ---------------------------------------------------------------------------

@bp.route("/harvest/seasons/<seasonId>/lodging-sites", methods=["POST"])
def create_lodging_site(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    body = get_json_body()
    require_fields(body, ["site_name", "state_code", "total_beds"])
    site_name = require_type(body, "site_name", "string")
    state_code = require_type(body, "state_code", "string")
    total_beds = require_type(body, "total_beds", "int")
    if total_beds <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "total_beds must be > 0")

    record = stamp_new(
        {
            "season_id": season["id"],
            "site_name": site_name,
            "state_code": state_code,
            "total_beds": total_beds,
        }
    )
    db.lodging_sites[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/seasons/<seasonId>/lodging-sites", methods=["GET"])
def list_sites_for_season(seasonId):
    require_roles(*ALL_ROLES)
    season = get_season_or_404(seasonId)
    pagination = parse_pagination(request.args)
    items = [s for s in db.lodging_sites.values() if s["season_id"] == season["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/lodging-sites", methods=["GET"])
def list_sites():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    items = list(db.lodging_sites.values())
    if season_id is not None:
        items = [s for s in items if s["season_id"] == season_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/lodging-sites/<siteId>", methods=["GET"])
def get_site(siteId):
    require_roles(*ALL_ROLES)
    site = get_site_or_404(siteId)
    return success_object(public(site))


# ---------------------------------------------------------------------------
# LodgingReservation
# ---------------------------------------------------------------------------

@bp.route("/harvest/route-stops/<stopId>/lodging-reservations", methods=["POST"])
def create_reservation(stopId):
    require_roles("CrewBoss")
    # Existence left-to-right: stop (path) → crew member (body FK) → site.
    stop = get_stop_or_404(stopId)
    body = get_json_body()
    require_fields(
        body,
        ["crew_member_id", "lodging_site_id", "stay_start_date", "stay_end_date"],
    )
    crew_member_id = require_type(body, "crew_member_id", "string")
    lodging_site_id = require_type(body, "lodging_site_id", "string")
    new_start = parse_date(body["stay_start_date"], "stay_start_date")
    new_end = parse_date(body["stay_end_date"], "stay_end_date")
    if new_end <= new_start:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "stay_end_date must be after stay_start_date (half-open interval)",
        )
    bed_count = body.get("bed_count", 1)
    if not isinstance(bed_count, int) or isinstance(bed_count, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "bed_count must be an integer")
    if bed_count <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "bed_count must be > 0")

    crew = get_crew_or_404(crew_member_id)
    site = get_site_or_404(lodging_site_id)

    # Aggregate per-night capacity (priority 8): beds are fungible — reject
    # if occupied + new bed_count would exceed total_beds on any night.
    relevant = [
        r
        for r in db.lodging_reservations.values()
        if r.get("lodging_site_id") == site["id"]
        and r["status"] in ("BOOKED", "CHECKED_IN")
    ]
    for night in daterange(new_start, new_end):
        occupied = 0
        for r in relevant:
            r_start = parse_date(r["stay_start_date"], "stay_start_date")
            r_end = parse_date(r["stay_end_date"], "stay_end_date")
            if r_start <= night < r_end:
                occupied += r.get("bed_count", 1)
        if occupied + bed_count > site["total_beds"]:
            raise ApiError(
                ERR_LODGING_CAPACITY_EXCEEDED,
                409,
                "Sum of bed_count across overlapping reservations would exceed site.total_beds on some night",
            )

    record = stamp_new(
        {
            "route_stop_id": stop["id"],
            "crew_member_id": crew["id"],
            "lodging_site_id": site["id"],
            "stay_start_date": body["stay_start_date"],
            "stay_end_date": body["stay_end_date"],
            "bed_count": bed_count,
            "status": "BOOKED",
        }
    )
    db.lodging_reservations[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/route-stops/<stopId>/lodging-reservations", methods=["GET"])
def list_reservations_for_stop(stopId):
    require_roles(*ALL_ROLES)
    stop = get_stop_or_404(stopId)
    pagination = parse_pagination(request.args)
    items = [
        r for r in db.lodging_reservations.values() if r["route_stop_id"] == stop["id"]
    ]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/lodging-reservations", methods=["GET"])
def list_reservations():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    route_stop_id = request.args.get("route_stop_id")
    crew_member_id = request.args.get("crew_member_id")
    items = list(db.lodging_reservations.values())
    if route_stop_id is not None:
        items = [r for r in items if r["route_stop_id"] == route_stop_id]
    if crew_member_id is not None:
        items = [r for r in items if r["crew_member_id"] == crew_member_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/lodging-reservations/<resId>", methods=["GET"])
def get_reservation(resId):
    require_roles(*ALL_ROLES)
    reservation = get_reservation_or_404(resId)
    return success_object(public(reservation))


@bp.route("/harvest/lodging-reservations/<resId>/check-in", methods=["POST"])
def check_in(resId):
    require_roles("CrewBoss")
    reservation = get_reservation_or_404(resId)
    if reservation["status"] != "BOOKED":
        raise ApiError(
            ERR_RESERVATION_NOT_BOOKED, 409, "check-in requires reservation BOOKED"
        )
    reservation["status"] = "CHECKED_IN"
    touch(reservation)
    return success_object(public(reservation))


@bp.route("/harvest/lodging-reservations/<resId>/check-out", methods=["POST"])
def check_out(resId):
    require_roles("CrewBoss")
    reservation = get_reservation_or_404(resId)
    if reservation["status"] != "CHECKED_IN":
        raise ApiError(
            ERR_RESERVATION_NOT_BOOKED,
            409,
            "check-out requires reservation CHECKED_IN",
        )
    reservation["status"] = "CHECKED_OUT"
    touch(reservation)
    return success_object(public(reservation))


@bp.route("/harvest/lodging-reservations/<resId>/cancel", methods=["POST"])
def cancel_reservation(resId):
    require_roles("CrewBoss")
    reservation = get_reservation_or_404(resId)
    if reservation["status"] != "BOOKED":
        raise ApiError(
            ERR_RESERVATION_NOT_CANCELLABLE,
            409,
            "cancel requires reservation BOOKED",
        )
    reservation["status"] = "CANCELLED"
    touch(reservation)
    return success_object(public(reservation))
