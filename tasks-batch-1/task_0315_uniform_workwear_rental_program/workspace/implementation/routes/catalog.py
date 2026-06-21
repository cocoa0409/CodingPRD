"""GarmentType and WashStation catalog endpoints (PRD §3.3)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, public_view, sort_by_created
from services import validate

bp = Blueprint("catalog", __name__)


# ---- Garment Types ----
@bp.route("/garment-types", methods=["POST"])
def create_garment_type():
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    body = validate.get_body()

    sku = validate.require_str(body, "sku")
    category = validate.require_enum(body, "category", validate.GARMENT_CATEGORIES)
    weekly_rate = validate.require_int(body, "weekly_rate_cents", minimum=0)
    replacement = validate.require_int(body, "replacement_cost_cents", minimum=0)
    emblem_setup = validate.require_int(body, "emblem_setup_cents", minimum=0)

    # sku globally unique.
    for gt in db.garment_types.values():
        if gt["sku"] == sku:
            raise errors.duplicate_key("sku already in use.")

    gt = make_record("garment_types", {
        "sku": sku,
        "category": category,
        "weekly_rate_cents": weekly_rate,
        "replacement_cost_cents": replacement,
        "emblem_setup_cents": emblem_setup,
    })
    return object_response(public_view(gt), 201)


@bp.route("/garment-types/<gt_id>", methods=["GET"])
def get_garment_type(gt_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager", "CleanroomTech"})
    gt = db.garment_types.get(gt_id)
    if gt is None:
        raise errors.not_found("Garment type not found.")
    return object_response(public_view(gt), 200)


@bp.route("/garment-types/<gt_id>/garments", methods=["GET"])
def list_type_garments(gt_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    if gt_id not in db.garment_types:
        raise errors.not_found("Garment type not found.")
    limit, offset = parse_pagination()
    rows = [g for g in db.garments.values() if g["garment_type_id"] == gt_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(g) for g in page], limit, offset, total)


# ---- Wash Stations ----
@bp.route("/wash-stations", methods=["POST"])
def create_wash_station():
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    body = validate.get_body()

    station_code = validate.require_str(body, "station_code")
    capacity = validate.require_int(body, "capacity", minimum=1)

    for s in db.wash_stations.values():
        if s["station_code"] == station_code:
            raise errors.duplicate_key("station_code already in use.")

    s = make_record("wash_stations", {
        "station_code": station_code,
        "capacity": capacity,
    })
    return object_response(public_view(s), 201)


@bp.route("/wash-stations/<station_id>", methods=["GET"])
def get_wash_station(station_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "CleanroomTech"})
    s = db.wash_stations.get(station_id)
    if s is None:
        raise errors.not_found("Wash station not found.")
    return object_response(public_view(s), 200)


@bp.route("/wash-stations/<station_id>/garments", methods=["GET"])
def list_station_garments(station_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "CleanroomTech"})
    if station_id not in db.wash_stations:
        raise errors.not_found("Wash station not found.")
    limit, offset = parse_pagination()
    rows = [g for g in db.garments.values() if g.get("wash_station_id") == station_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(g) for g in page], limit, offset, total)
