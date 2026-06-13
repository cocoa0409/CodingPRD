"""Sections, Seats, SeasonPlans, ParkingZones — inventory + template CRUD."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (
    get_json_body,
    get_or_404,
    paginate,
    require_enum,
    require_int,
    require_str,
    require_str_field,
    parking_zone_view,
    season_plan_view,
    seat_view,
    section_view,
)
from middleware import get_auth, require_role
from response import success, success_list

bp = Blueprint("inventory", __name__)

ALL_ROLES = {"BoxOfficeAgent", "AccountHolder", "FinanceClerk"}


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------
@bp.route("/sections", methods=["POST"])
def create_section():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    name = require_str(body, "name")
    tier = require_enum(body, "tier", {"PREMIUM", "STANDARD", "VALUE"})
    base_price = require_int(body, "base_price_cents", minimum=0)
    with db.lock:
        row = db.new_common()
        row.update({"name": name, "tier": tier, "base_price_cents": base_price})
        db.sections[row["id"]] = row
        return success(section_view(row), 201)


@bp.route("/sections/<rid>", methods=["GET"])
def get_section(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.sections, rid)
        return success(section_view(row))


@bp.route("/sections", methods=["GET"])
def list_sections():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    tier = request.args.get("tier")
    with db.lock:
        rows = [r for r in db.sections.values() if tier is None or r["tier"] == tier]
        page, limit, offset, total = paginate(rows)
        return success_list([section_view(r) for r in page], limit, offset, total)


@bp.route("/sections/<rid>/seats", methods=["GET"])
def list_section_seats(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    with db.lock:
        get_or_404(db.sections, rid)
        rows = [
            s
            for s in db.seats.values()
            if s["section_id"] == rid and (status is None or s["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([seat_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Seat
# ---------------------------------------------------------------------------
@bp.route("/seats", methods=["POST"])
def create_seat():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    section_id = require_str(body, "section_id")
    with db.lock:
        section = db.sections.get(section_id)
        if section is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "section_id not found")
        row_label = require_str(body, "row_label")
        seat_number = require_int(body, "seat_number", minimum=1)
        season_start = require_str_field(body, "season_start_date")
        season_end = require_str_field(body, "season_end_date")
        row = db.new_common()
        row.update(
            {
                "section_id": section_id,
                "row_label": row_label,
                "seat_number": seat_number,
                "season_start_date": season_start,
                "season_end_date": season_end,
                "status": "AVAILABLE",
            }
        )
        db.seats[row["id"]] = row
        # Section counters are derived; bump version/updated_at for the change.
        db.touch(section)
        return success(seat_view(row), 201)


@bp.route("/seats/<rid>", methods=["GET"])
def get_seat(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.seats, rid)
        return success(seat_view(row))


@bp.route("/seats", methods=["GET"])
def list_seats():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    section_id = request.args.get("section_id")
    status = request.args.get("status")
    with db.lock:
        rows = [
            s
            for s in db.seats.values()
            if (section_id is None or s["section_id"] == section_id)
            and (status is None or s["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([seat_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# SeasonPlan
# ---------------------------------------------------------------------------
@bp.route("/season-plans", methods=["POST"])
def create_season_plan():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    name = require_str(body, "name")
    plan_type = require_enum(body, "plan_type", {"FULL", "PARTIAL"})
    game_count = require_int(body, "game_count", minimum=1)
    multiplier = require_int(body, "price_multiplier_bps", minimum=0, maximum=10000)
    from helpers import optional_bool

    includes_playoffs = optional_bool(body, "includes_playoffs", False)
    with db.lock:
        row = db.new_common()
        row.update(
            {
                "name": name,
                "plan_type": plan_type,
                "game_count": game_count,
                "price_multiplier_bps": multiplier,
                "includes_playoffs": includes_playoffs,
            }
        )
        db.season_plans[row["id"]] = row
        return success(season_plan_view(row), 201)


@bp.route("/season-plans/<rid>", methods=["GET"])
def get_season_plan(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.season_plans, rid)
        return success(season_plan_view(row))


@bp.route("/season-plans", methods=["GET"])
def list_season_plans():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    plan_type = request.args.get("plan_type")
    with db.lock:
        rows = [
            r
            for r in db.season_plans.values()
            if plan_type is None or r["plan_type"] == plan_type
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([season_plan_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# ParkingZone
# ---------------------------------------------------------------------------
@bp.route("/parking-zones", methods=["POST"])
def create_parking_zone():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    name = require_str(body, "name")
    capacity = require_int(body, "capacity", minimum=0)
    price_cents = require_int(body, "price_cents", minimum=0)
    with db.lock:
        row = db.new_common()
        row.update({"name": name, "capacity": capacity, "price_cents": price_cents})
        db.parking_zones[row["id"]] = row
        return success(parking_zone_view(row), 201)


@bp.route("/parking-zones/<rid>", methods=["GET"])
def get_parking_zone(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.parking_zones, rid)
        return success(parking_zone_view(row))


@bp.route("/parking-zones", methods=["GET"])
def list_parking_zones():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        rows = list(db.parking_zones.values())
        page, limit, offset, total = paginate(rows)
        return success_list([parking_zone_view(r) for r in page], limit, offset, total)
