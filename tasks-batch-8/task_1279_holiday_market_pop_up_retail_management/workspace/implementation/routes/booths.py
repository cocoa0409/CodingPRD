"""Booth endpoints."""
from flask import Blueprint

import db
from middleware import auth, require_roles
from response import success
from services.core import (
    BOOTH_TYPES,
    ZONES,
    arg,
    as_bool,
    as_enum,
    as_int,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
)

bp = Blueprint("booths", __name__)

MO = ("MarketOperator",)
GET_ROLES = ("MarketOperator", "VendorRole", "JuryChair", "UtilityCrew")


@bp.post("/markets/<marketId>/booths")
def create_booth(marketId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    data = body()
    booth_code = as_str(required(data, "booth_code"), "booth_code")
    booth_type = as_enum(required(data, "booth_type"), "booth_type", BOOTH_TYPES)
    zone = as_enum(required(data, "zone"), "zone", ZONES)
    square_feet = as_int(required(data, "square_feet"), "square_feet")
    has_power = as_bool(data.get("has_power", False), "has_power")
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "booth_code": booth_code,
            "booth_type": booth_type,
            "zone": zone,
            "square_feet": square_feet,
            "has_power": has_power,
            "status": "AVAILABLE",
            "_reserved_for_assignment_id": None,
        }
    )
    # PRD 2.4: id is server-minted and created_at is set at creation; any
    # client-supplied system fields are ignored.
    db.STORES["booths"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/booths/<boothId>")
def get_booth(marketId, boothId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    return success(serialize(get_child("booths", boothId, marketId)))


@bp.get("/markets/<marketId>/booths")
def list_booths(marketId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    status = arg("status")
    booth_type = arg("booth_type")
    zone = arg("zone")
    records = []
    for b in db.STORES["booths"].values():
        if b["market_id"] != marketId:
            continue
        if status is not None and b["status"] != status:
            continue
        if booth_type is not None and b["booth_type"] != booth_type:
            continue
        if zone is not None and b["zone"] != zone:
            continue
        records.append(b)
    return list_response(records)
