"""Station endpoints."""

from flask import Blueprint, g, request

import db
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from validators import (
    get_pagination,
    paginate_list,
    parse_json_body,
    require_int,
    require_number,
    require_str,
)


bp = Blueprint("stations", __name__)


@bp.post("/stations")
@require_roles({"PlatformOperator", "StationOwner"})
def create_station():
    body = parse_json_body()
    name = require_str(body, "name", 1, 120)
    operator_id = require_str(body, "operator_id")
    station_owner_id = require_str(body, "station_owner_id")
    latitude = require_number(body, "latitude", -90.0, 90.0, max_frac_digits=6)
    longitude = require_number(body, "longitude", -180.0, 180.0, max_frac_digits=6)
    revenue_share_bps = require_int(body, "revenue_share_bps", 0, 10_000)

    if operator_id not in db.operators:
        raise_error("ERR_NOT_FOUND", "operator_id not found")
    if station_owner_id not in db.operators:
        raise_error("ERR_NOT_FOUND", "station_owner_id not found")

    # StationOwner may only create their own owned stations.
    if g.role == "StationOwner" and g.user_id != station_owner_id:
        raise_error("ERR_FORBIDDEN", "StationOwner can only create owned stations")

    # Uniqueness of name within operator_id.
    for existing in db.stations.values():
        if existing["operator_id"] == operator_id and existing["name"] == name:
            raise_error("ERR_VALIDATION", "station name not unique within operator")

    record = {
        "name": name,
        "operator_id": operator_id,
        "station_owner_id": station_owner_id,
        "latitude": latitude,
        "longitude": longitude,
        "revenue_share_bps": revenue_share_bps,
        "status": "ACTIVE",
    }
    db.with_common_fields(record)
    db.stations[record["id"]] = record
    return success(db.public(record), status=201)


@bp.get("/stations")
@require_roles({"PlatformOperator", "StationOwner", "EVDriver",
                "FieldTechnician", "CustomerService"})
def list_stations():
    operator_id = request.args.get("operator_id")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = sorted(db.stations.values(), key=lambda r: r["_seq"])
    if operator_id:
        items = [s for s in items if s["operator_id"] == operator_id]
    if status:
        items = [s for s in items if s["status"] == status]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)


@bp.get("/stations/<station_id>")
@require_roles({"PlatformOperator", "StationOwner", "EVDriver",
                "FieldTechnician", "CustomerService"})
def get_station(station_id: str):
    record = db.stations.get(station_id)
    if record is None:
        raise_error("ERR_NOT_FOUND", "station not found")
    return success(db.public(record))
