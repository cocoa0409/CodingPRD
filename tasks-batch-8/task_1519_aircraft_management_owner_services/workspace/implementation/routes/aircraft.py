"""Aircraft endpoints."""
from flask import Blueprint, request

from db import db
from errors import validation, ApiError, ERR_TAIL_NUMBER_EXISTS
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import aircraft_view
from services.core import make_record, require_exists, filter_value_exists, get_pagination, paginate

bp = Blueprint("aircraft", __name__)


@bp.route("/aircraft", methods=["POST"])
def create_aircraft():
    require_roles("AccountExecutive")
    body = request.get_json(silent=True) or {}
    owner_id = body.get("owner_id")
    tail_number = body.get("tail_number")
    model = body.get("model")
    home_base_icao = body.get("home_base_icao")

    # existence of FK reference
    if owner_id is not None:
        require_exists(db.owners, owner_id, "owner_id does not resolve")

    for field, value in (("owner_id", owner_id), ("tail_number", tail_number),
                         ("model", model), ("home_base_icao", home_base_icao)):
        if not isinstance(value, str) or not value:
            raise validation(f"{field} is required")
    # owner_id presence implies resolution above
    require_exists(db.owners, owner_id, "owner_id does not resolve")

    for other in db.aircraft.values():
        if other["tail_number"] == tail_number:
            raise ApiError(ERR_TAIL_NUMBER_EXISTS, "tail_number already registered", 409)

    rec = make_record({
        "owner_id": owner_id,
        "tail_number": tail_number,
        "model": model,
        "home_base_icao": home_base_icao,
        "total_time_hours": 0.0,
    })
    db.aircraft[rec["id"]] = rec
    return success_object(aircraft_view(rec), 201)


@bp.route("/aircraft/<aircraft_id>", methods=["GET"])
def get_aircraft(aircraft_id):
    require_read()
    rec = require_exists(db.aircraft, aircraft_id)
    return success_object(aircraft_view(rec))


@bp.route("/aircraft", methods=["GET"])
def list_aircraft():
    require_read()
    owner_id = request.args.get("owner_id")
    filter_value_exists(db.owners, owner_id)
    limit, offset = get_pagination(request.args)
    records = list(db.aircraft.values())
    if owner_id is not None:
        records = [r for r in records if r["owner_id"] == owner_id]
    page, total = paginate(records, limit, offset)
    return success_list([aircraft_view(r) for r in page], limit, offset, total)
